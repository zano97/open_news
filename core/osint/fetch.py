"""Recupero di pagine web per l'OSINT e per il testo integrale.

Motore: **Scrapling** (BSD-3, software libero) quando l'extra
``[osint]`` è installato, altrimenti il client httpx di sempre.
Scrapling serve per una ragione precisa: molte pagine informative delle
testate (e alcuni articoli) sono renderizzate via JavaScript e con la
sola HTTP non esistono. Un browser vero le vede.

**Dove passa la linea** (ADR-0027): usiamo Scrapling per RENDERIZZARE
pagine pubbliche, mai per aggirare una protezione. Restano spente le
funzioni di elusione anti-bot (risoluzione di Cloudflare/Turnstile,
falsificazione dell'impronta per fingersi un utente umano): se un sito
ci nega l'accesso, la risposta è rispettarlo e coprirlo via GDELT, non
travestirsi. robots.txt continua a governare il crawling, e ogni
richiesta si presenta col nostro User-Agent.
"""

import logging
from dataclasses import dataclass

import httpx

from core.config import get_settings
from core.ingest.ratelimit import DomainRateLimiter
from core.ingest.robots import RobotsCache
from core.net import EgressDeniedError

log = logging.getLogger(__name__)

# Elusione anti-bot: spenta per scelta, non per dimenticanza (ADR-0027).
BYPASS_ANTIBOT = False

_scrapling_pronto: bool | None = None


def scrapling_disponibile() -> bool:
    """Vero se l'extra [osint] è installato (import verificato una volta)."""
    global _scrapling_pronto
    if _scrapling_pronto is None:
        try:
            import scrapling  # noqa: F401

            _scrapling_pronto = True
        except ImportError:
            _scrapling_pronto = False
            log.info(
                "scrapling non installato: le pagine renderizzate via "
                "JavaScript restano fuori portata (extra [osint])"
            )
    return bool(_scrapling_pronto)


def reset_scrapling_cache() -> None:
    """Per i test."""
    global _scrapling_pronto
    _scrapling_pronto = None


@dataclass
class Pagina:
    url: str
    html: str = ""
    status: int | None = None
    motore: str = "httpx"
    error: str | None = None

    @property
    def ok(self) -> bool:
        return bool(self.html) and self.error is None


def _rendi_con_scrapling(url: str, timeout_ms: int) -> Pagina:
    """Rendering in un browser reale (Playwright via Scrapling), sincrono.

    Va chiamato in un thread: il browser blocca. Nessuna elusione:
    niente risoluzione di captcha, niente impronte falsificate.
    """
    from scrapling.fetchers import DynamicFetcher

    pagina = Pagina(url=url, motore="scrapling")
    try:
        risposta = DynamicFetcher.fetch(
            url,
            headless=True,
            network_idle=True,
            timeout=timeout_ms,
            extra_headers={"User-Agent": get_settings().user_agent},
        )
    except Exception as exc:  # browser assente, timeout, pagina ostile
        pagina.error = f"{exc.__class__.__name__}: {exc}"
        return pagina
    pagina.status = getattr(risposta, "status", None)
    pagina.html = getattr(risposta, "html_content", "") or str(risposta)
    if pagina.status is not None and pagina.status >= 400:
        pagina.error = f"HTTP {pagina.status}"
    return pagina


async def scarica_pagina(
    url: str,
    *,
    client: httpx.AsyncClient,
    limiter: DomainRateLimiter,
    robots: RobotsCache,
    rendi: bool = True,
    timeout_ms: int = 20_000,
) -> Pagina:
    """Una pagina web pubblica, nel rispetto di robots.txt.

    Prima la via leggera (HTTP semplice); se la pagina non ha contenuto
    utile — tipico dei siti che si disegnano in JavaScript — e Scrapling
    è disponibile, si ripete con un browser vero.
    """
    pagina = Pagina(url=url)
    # Questa è navigazione di pagine, non lettura di feed: robots vale.
    if not await robots.can_fetch(url):
        pagina.error = "robots.txt vieta l'accesso"
        return pagina
    from urllib.parse import urlsplit

    await limiter.wait(urlsplit(url).hostname or "")
    try:
        resp = await client.get(url)
        pagina.status = resp.status_code
        if resp.status_code == 200:
            pagina.html = resp.text
        else:
            pagina.error = f"HTTP {resp.status_code}"
    except (httpx.HTTPError, EgressDeniedError) as exc:
        pagina.error = f"{exc.__class__.__name__}"

    if not rendi or not scrapling_disponibile():
        return pagina
    # Pagina vuota o scheletro JS: vale un rendering vero.
    scheletro = len(pagina.html) < 2000 or "<body" not in pagina.html.lower()
    if pagina.ok and not scheletro:
        return pagina
    import asyncio

    resa = await asyncio.to_thread(_rendi_con_scrapling, url, timeout_ms)
    return resa if resa.ok else pagina

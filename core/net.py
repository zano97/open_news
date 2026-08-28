"""Uscita di rete controllata: un solo punto di costruzione dei client HTTP.

Vincolo di progetto: nessuna chiamata verso servizi a pagamento. Ogni client
costruito qui rifiuta le richieste verso host fuori dall'allowlist, composta
da: infrastruttura gratuita documentata (GDELT, Wikidata, registri pubblici),
host interni allo stack (senza punto nel nome, localhost) e i domini delle
fonti del catalogo. Il test `tests/test_net.py` verifica il comportamento.
"""

import ipaddress
import os
from functools import lru_cache
from typing import Any
from urllib.parse import urlsplit

import httpx

from core.config import get_settings

# Infrastruttura gratuita e documentata (vedi NOTICE): suffissi di dominio.
STATIC_ALLOWED_SUFFIXES: frozenset[str] = frozenset(
    {
        "api.gdeltproject.org",  # GDELT DOC 2.0, senza chiave, con citazione
        "wikidata.org",  # fatti societari, CC0
        "dbpedia.org",  # entity linking di riserva
        "agcom.it",  # ROC — registro operatori di comunicazione
        "informazioneeditoria.gov.it",  # contributi diretti all'editoria
        "media-ownership.eu",  # EurOMo, CC BY 4.0
        "raw.githubusercontent.com",  # font OFL e asset vendorizzati (solo script di setup)
        "argosopentech.com",  # modelli di traduzione Argos (solo script di setup)
        "public.api.bsky.app",  # AppView pubblica Bluesky, senza chiave (vedi NOTICE)
        "test",  # dominio riservato RFC 2606: usato solo nei test
    }
)


class EgressDeniedError(RuntimeError):
    """Richiesta verso un host fuori dall'allowlist: mai silenziata."""

    def __init__(self, host: str) -> None:
        super().__init__(
            f"richiesta HTTP verso host non in allowlist: {host!r}. "
            "Se è una nuova fonte, aggiungila a data/sources.yaml; se è un "
            "servizio, deve essere gratuito e documentato in core/net.py e NOTICE."
        )
        self.host = host


def _catalog_hosts() -> frozenset[str]:
    """Domini delle fonti dal catalogo: dominio testata, host dei feed e
    istanze Mastodon dei canali social dichiarati."""
    # Import locale per evitare dipendenze circolari con core.ingest.
    from core.ingest.catalog import load_catalog

    hosts: set[str] = set()
    for src in load_catalog():
        hosts.add(src.domain.lower())
        for feed in src.feed_urls:
            host = urlsplit(feed).hostname
            if host:
                hosts.add(host.lower())
        for url in src.social.values():
            host = urlsplit(url).hostname if "://" in url else None
            if host:
                hosts.add(host.lower())
    return frozenset(hosts)


@lru_cache(maxsize=1)
def allowed_suffixes() -> frozenset[str]:
    return STATIC_ALLOWED_SUFFIXES | _catalog_hosts()


def host_allowed(host: str) -> bool:
    host = host.lower().rstrip(".")
    # Host interni allo stack (meilisearch, ollama, db) e loopback.
    if host in {"localhost"} or "." not in host:
        return True
    # Alias Docker verso la macchina host (Docker Desktop su macOS/Windows):
    # serve per raggiungere un Ollama che gira sul computer, fuori dai container.
    if host in {"host.docker.internal", "gateway.docker.internal"}:
        return True
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return ipaddress.ip_address(host).is_private or ipaddress.ip_address(host).is_loopback
    return any(host == suffix or host.endswith("." + suffix) for suffix in allowed_suffixes())


async def _guard_request(request: httpx.Request) -> None:
    host = request.url.host
    if not host_allowed(host):
        raise EgressDeniedError(host)


def build_client(
    *,
    timeout: float | None = None,
    follow_redirects: bool = True,
) -> httpx.AsyncClient:
    """Client HTTP con User-Agent identificativo e guardia sull'egress.

    Tutto il codice del progetto che parla con l'esterno DEVE passare da qui.
    """
    settings = get_settings()
    base = timeout if timeout is not None else settings.http_timeout_seconds
    extra: dict[str, Any] = {}
    # Un transport esplicito disattiverebbe il supporto proxy di httpx
    # (HTTPS_PROXY & co.): lo usiamo solo quando NON c'è un proxy. Dà due
    # cose: retries=2 sui tentativi di CONNESSIONE (DNS+TCP+TLS) e, di
    # default, socket IPv4 — httpx non ha l'happy-eyeballs e su reti con
    # IPv6 annunciato ma rotto le connessioni scadrebbero in ConnectTimeout
    # senza mai provare IPv4 (vedi Settings.http_ipv4_only).
    proxy_attivo = any(
        os.environ.get(k)
        for k in (
            "HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy",
            "ALL_PROXY", "all_proxy",
        )
    )
    if not proxy_attivo:
        extra["transport"] = httpx.AsyncHTTPTransport(
            retries=1,
            local_address="0.0.0.0" if settings.http_ipv4_only else None,
        )
    return httpx.AsyncClient(
        headers={
            "User-Agent": settings.user_agent,
            # Alcuni server rifiutano richieste senza Accept; la preferenza
            # XML aiuta i feed, */* copre JSON (GDELT, Wikidata) e HTML.
            "Accept": (
                "application/rss+xml, application/atom+xml, "
                "application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5"
            ),
        },
        timeout=httpx.Timeout(base, connect=min(10.0, base)),
        follow_redirects=follow_redirects,
        event_hooks={"request": [_guard_request]},
        **extra,
    )


def reset_allowlist_cache() -> None:
    """Per test e per ricarichi del catalogo."""
    allowed_suffixes.cache_clear()

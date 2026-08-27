"""Copertura mondiale via GDELT DOC 2.0 API (gratuita, senza chiave).

Usata per le fonti senza RSS pubblico (Reuters, AP) e come integrazione di
copertura per tutte le altre. GDELT chiede citazione con link: vedi NOTICE e
il piè di pagina del sito. Di GDELT si usano solo metadati: titolo, URL,
lingua, data, immagine sociale — mai contenuti.

Cortesia e robustezza: max 1 richiesta ogni 5 s (override del rate limiter);
i domini vengono interrogati IN BATCH (`(domain:a OR domain:b ...)`) così un
catalogo di ~100 testate costa una decina di richieste, non cento; su 429 e
5xx si riprova con attesa crescente, rispettando l'eventuale Retry-After.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.extract.canonical import canonicalize
from core.extract.dedup import simhash64, to_hex
from core.ingest.ratelimit import DomainRateLimiter
from core.models import Article, Source
from core.provenance import record

log = logging.getLogger(__name__)

GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_HOST = "api.gdeltproject.org"
RETRY_ATTEMPTS = 3
RETRY_BASE_SECONDS = 10.0


class GdeltFormatError(ValueError):
    """GDELT ha risposto 200 ma non con il JSON atteso (succede sotto carico)."""

# GDELT usa nomi di lingua per esteso; mappiamo le più comuni nel catalogo.
_LANGUAGE_NAMES = {
    "english": "en", "italian": "it", "french": "fr", "german": "de",
    "spanish": "es", "portuguese": "pt", "dutch": "nl", "russian": "ru",
    "ukrainian": "uk", "arabic": "ar", "hebrew": "he", "japanese": "ja",
    "chinese": "zh", "hindi": "hi", "korean": "ko", "turkish": "tr",
}


@dataclass(frozen=True)
class GdeltArticle:
    url: str
    title: str
    language: str | None
    seen_at: datetime | None
    image_url: str | None
    domain: str | None
    source_country: str | None


def _parse_seendate(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def parse_artlist(payload: dict[str, Any]) -> list[GdeltArticle]:
    articles: list[GdeltArticle] = []
    for item in payload.get("articles", []) or []:
        url = item.get("url")
        title = (item.get("title") or "").strip()
        if not url or not title:
            continue
        articles.append(
            GdeltArticle(
                url=str(url),
                title=title,
                language=_LANGUAGE_NAMES.get(str(item.get("language", "")).lower()),
                seen_at=_parse_seendate(item.get("seendate")),
                image_url=item.get("socialimage") or None,
                domain=item.get("domain"),
                source_country=item.get("sourcecountry"),
            )
        )
    return articles


def error_text(exc: Exception) -> str:
    text = str(exc).strip()
    return f"{exc.__class__.__name__}: {text}" if text else exc.__class__.__name__


def _retry_after_seconds(resp: httpx.Response, attempt: int) -> float:
    header = resp.headers.get("Retry-After", "")
    try:
        return max(float(header), 1.0)
    except ValueError:
        return float(RETRY_BASE_SECONDS * (2**attempt))


async def _get_artlist(
    client: httpx.AsyncClient,
    limiter: DomainRateLimiter,
    query: str,
    *,
    timespan: str,
    max_records: int,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> list[GdeltArticle]:
    """GET con retry: 429/5xx e timeout si ritentano con attesa crescente."""
    params = {
        "query": query,
        "mode": "artlist",
        "format": "json",
        "maxrecords": str(max_records),
        "timespan": timespan,
        "sort": "datedesc",
    }
    last_error: Exception | None = None
    for attempt in range(RETRY_ATTEMPTS):
        await limiter.wait(GDELT_HOST)
        try:
            resp = await client.get(GDELT_DOC_URL, params=params)
            if resp.status_code == 429 or resp.status_code >= 500:
                last_error = httpx.HTTPStatusError(
                    f"HTTP {resp.status_code}", request=resp.request, response=resp
                )
                await sleep(_retry_after_seconds(resp, attempt))
                continue
            resp.raise_for_status()
            try:
                payload = resp.json()
            except ValueError as exc:
                # Sotto carico GDELT può rispondere 200 con testo semplice.
                snippet = resp.text.strip().replace("\n", " ")[:120]
                raise GdeltFormatError(
                    f"risposta non JSON ({snippet or 'vuota'})"
                ) from exc
            return parse_artlist(payload)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = exc
            await sleep(RETRY_BASE_SECONDS * (2**attempt))
    assert last_error is not None
    raise last_error


async def fetch_domain_articles(
    client: httpx.AsyncClient,
    limiter: DomainRateLimiter,
    domain: str,
    *,
    timespan: str = "24h",
    max_records: int = 100,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> list[GdeltArticle]:
    return await _get_artlist(
        client, limiter, f"domain:{domain}",
        timespan=timespan, max_records=max_records, sleep=sleep,
    )


async def fetch_domains_articles(
    client: httpx.AsyncClient,
    limiter: DomainRateLimiter,
    domains: Sequence[str],
    *,
    timespan: str = "24h",
    max_records: int = 250,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> list[GdeltArticle]:
    """Una sola richiesta per un gruppo di domini (query con OR)."""
    if not domains:
        return []
    if len(domains) == 1:
        query = f"domain:{domains[0]}"
    else:
        query = "(" + " OR ".join(f"domain:{d}" for d in domains) + ")"
    return await _get_artlist(
        client, limiter, query, timespan=timespan, max_records=max_records, sleep=sleep
    )


def match_source(item: GdeltArticle, sources: Sequence[Source]) -> Source | None:
    """Attribuisce un risultato GDELT alla fonte del catalogo per dominio."""
    domain = (item.domain or "").lower().removeprefix("www.")
    if not domain:
        return None
    for source in sources:
        wanted = (source.gdelt_domain or "").lower()
        if wanted and (domain == wanted or domain.endswith("." + wanted)):
            return source
    return None


async def store_gdelt_articles(
    session: AsyncSession,
    source: Source,
    items: Sequence[GdeltArticle],
    *,
    query: str,
    timespan: str,
) -> int:
    """Registra come articoli i risultati GDELT di una fonte. Idempotente."""
    if not items:
        return 0
    known = set(
        (
            await session.execute(
                select(Article.url).where(Article.url.in_([a.url for a in items]))
            )
        ).scalars()
    )
    created = 0
    for item in items:
        if item.url in known:
            continue
        article = Article(
            source_id=source.id,
            url=item.url,
            canonical_url=canonicalize(item.url),
            title=item.title,
            snippet="",  # GDELT non fornisce estratti: nessun contenuto oltre il titolo
            image_url=item.image_url,
            published_at=item.seen_at,
            language=item.language or source.language,
            simhash=to_hex(simhash64(item.title)),
        )
        session.add(article)
        await session.flush()
        await record(
            session,
            entity_type="article",
            entity_id=article.id,
            field="ingest",
            method="gdelt-doc-2.0",
            inputs={"query": query, "timespan": timespan},
            source_name="The GDELT Project",
            source_url="https://www.gdeltproject.org/",
        )
        known.add(item.url)
        created += 1
    return created


async def ingest_gdelt_source(
    session: AsyncSession,
    source: Source,
    *,
    client: httpx.AsyncClient,
    limiter: DomainRateLimiter,
    timespan: str = "24h",
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> int:
    """Registra come articoli i risultati GDELT per il dominio della fonte."""
    if not source.gdelt_domain:
        return 0
    try:
        found = await fetch_domain_articles(
            client, limiter, source.gdelt_domain, timespan=timespan, sleep=sleep
        )
    except (httpx.HTTPError, GdeltFormatError) as exc:
        log.warning("GDELT %s: %s", source.gdelt_domain, error_text(exc))
        return 0
    return await store_gdelt_articles(
        session, source, found,
        query=f"domain:{source.gdelt_domain}", timespan=timespan,
    )

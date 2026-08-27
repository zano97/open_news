"""Copertura mondiale via GDELT DOC 2.0 API (gratuita, senza chiave).

Usata per le fonti senza RSS pubblico (Reuters, AP) e come integrazione di
copertura per paese/tema. GDELT chiede citazione con link: vedi NOTICE e il
piè di pagina del sito. Throttling: max 1 richiesta ogni 5 s (override del
rate limiter). Di GDELT si usano solo metadati: titolo, URL, lingua, data,
immagine sociale — mai contenuti.
"""

import logging
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


async def fetch_domain_articles(
    client: httpx.AsyncClient,
    limiter: DomainRateLimiter,
    domain: str,
    *,
    timespan: str = "24h",
    max_records: int = 100,
) -> list[GdeltArticle]:
    await limiter.wait(GDELT_HOST)
    resp = await client.get(
        GDELT_DOC_URL,
        params={
            "query": f"domain:{domain}",
            "mode": "artlist",
            "format": "json",
            "maxrecords": str(max_records),
            "timespan": timespan,
            "sort": "datedesc",
        },
    )
    resp.raise_for_status()
    return parse_artlist(resp.json())


async def ingest_gdelt_source(
    session: AsyncSession,
    source: Source,
    *,
    client: httpx.AsyncClient,
    limiter: DomainRateLimiter,
    timespan: str = "24h",
) -> int:
    """Registra come articoli i risultati GDELT per il dominio della fonte."""
    if not source.gdelt_domain:
        return 0
    try:
        found = await fetch_domain_articles(
            client, limiter, source.gdelt_domain, timespan=timespan
        )
    except httpx.HTTPError as exc:
        log.warning("GDELT %s: %s", source.gdelt_domain, exc)
        return 0

    if not found:
        return 0
    known = set(
        (
            await session.execute(
                select(Article.url).where(Article.url.in_([a.url for a in found]))
            )
        ).scalars()
    )
    created = 0
    for item in found:
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
            inputs={"query": f"domain:{source.gdelt_domain}", "timespan": timespan},
            source_name="The GDELT Project",
            source_url="https://www.gdeltproject.org/",
        )
        known.add(item.url)
        created += 1
    return created

"""Testo integrale per l'analisi locale: scaricato nel rispetto di robots.txt,
mai mostrato né ridistribuito (colonna interna `Article.full_text`).

Estrazione con trafilatura; nessun fallback pesante: se l'estrazione fallisce
l'articolo resta analizzabile da titolo e snippet.
"""

import logging
from urllib.parse import urlsplit

import httpx
import trafilatura
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.ingest.ratelimit import DomainRateLimiter
from core.ingest.robots import RobotsCache
from core.models import Article

log = logging.getLogger(__name__)

FULLTEXT_MAX_CHARS = 100_000


def extract_text(html: str, url: str | None = None) -> str | None:
    text = trafilatura.extract(
        html,
        url=url,
        include_comments=False,
        include_tables=False,
        favor_precision=True,
    )
    if not text:
        return None
    return text[:FULLTEXT_MAX_CHARS]


async def fetch_fulltext(
    session: AsyncSession,
    article: Article,
    *,
    client: httpx.AsyncClient,
    limiter: DomainRateLimiter,
    robots: RobotsCache,
) -> bool:
    """Scarica e salva il testo integrale di un articolo. True se riuscito."""
    if article.full_text:
        return True
    if not await robots.can_fetch(article.url):
        log.info("robots.txt vieta il testo integrale di %s", article.url)
        return False
    host = urlsplit(article.url).hostname or ""
    await limiter.wait(host)
    try:
        resp = await client.get(article.url)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("fulltext %s: %s", article.url, exc)
        return False
    text = extract_text(resp.text, url=article.url)
    if text is None:
        return False
    article.full_text = text
    await session.flush()
    return True


async def articles_missing_fulltext(
    session: AsyncSession, limit: int = 25
) -> list[Article]:
    rows = (
        await session.execute(
            select(Article)
            .where(Article.full_text.is_(None), Article.snippet != "")
            .order_by(Article.id.desc())
            .limit(limit)
        )
    ).scalars()
    return list(rows)

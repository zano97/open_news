"""Job di raccolta: catalogo, feed RSS, GDELT, testo integrale.

Ogni job apre le proprie risorse (client HTTP con guardia egress, rate
limiter, cache robots) e le chiude a fine esecuzione; le sessioni DB sono
per-fonte, così un errore su una testata non blocca le altre.
"""

import logging

from sqlalchemy import select

from core.db import get_sessionmaker
from core.extract.fulltext import articles_missing_fulltext, fetch_fulltext
from core.ingest.catalog import sync_catalog
from core.ingest.gdelt import ingest_gdelt_source
from core.ingest.ratelimit import DomainRateLimiter
from core.ingest.robots import RobotsCache
from core.ingest.rss import ingest_feed
from core.models import Source
from core.net import build_client

log = logging.getLogger(__name__)


async def sync_catalog_job() -> None:
    maker = get_sessionmaker()
    async with maker() as session:
        stats = await sync_catalog(session)
        await session.commit()
    log.info("catalogo sincronizzato: %s", stats)


async def ingest_feeds_job() -> None:
    maker = get_sessionmaker()
    async with build_client() as client:
        limiter = DomainRateLimiter()
        robots = RobotsCache(client)
        async with maker() as session:
            sources = list(
                (
                    await session.execute(
                        select(Source).where(Source.enabled, Source.feed_urls != [])
                    )
                ).scalars()
            )
        for source in sources:
            if not source.feed_urls:
                continue
            async with maker() as session:
                merged = await session.merge(source, load=False)
                for feed_url in merged.feed_urls:
                    stats = await ingest_feed(
                        session, merged, feed_url,
                        client=client, limiter=limiter, robots=robots,
                    )
                    if stats.error:
                        log.warning("%s %s: %s", merged.slug, feed_url, stats.error)
                    elif stats.created:
                        log.info("%s: +%d articoli da %s", merged.slug, stats.created, feed_url)
                await session.commit()


async def ingest_gdelt_job() -> None:
    maker = get_sessionmaker()
    async with build_client() as client:
        limiter = DomainRateLimiter()
        async with maker() as session:
            # Complemento di copertura per TUTTE le fonti: GDELT vede anche
            # articoli assenti dai feed RSS (il dedup per URL evita i doppi).
            sources = list(
                (
                    await session.execute(
                        select(Source).where(
                            Source.enabled, Source.gdelt_domain.is_not(None)
                        )
                    )
                ).scalars()
            )
        for source in sources:
            async with maker() as session:
                merged = await session.merge(source, load=False)
                created = await ingest_gdelt_source(
                    session, merged, client=client, limiter=limiter
                )
                await session.commit()
                if created:
                    log.info("%s: +%d articoli via GDELT", merged.slug, created)


async def fetch_fulltext_job(limit: int = 25) -> None:
    maker = get_sessionmaker()
    async with build_client() as client:
        limiter = DomainRateLimiter()
        robots = RobotsCache(client)
        async with maker() as session:
            articles = await articles_missing_fulltext(session, limit=limit)
            done = 0
            for article in articles:
                if await fetch_fulltext(
                    session, article, client=client, limiter=limiter, robots=robots
                ):
                    done += 1
            await session.commit()
    if done:
        log.info("testo integrale scaricato per %d articoli", done)

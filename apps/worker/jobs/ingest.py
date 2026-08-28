"""Job di raccolta: catalogo, feed RSS, GDELT, testo integrale.

Ogni job apre le proprie risorse (client HTTP con guardia egress, rate
limiter, cache robots) e le chiude a fine esecuzione; le sessioni DB sono
per-fonte, così un errore su una testata non blocca le altre.
"""

import logging

from core.db import get_sessionmaker
from core.extract.fulltext import articles_missing_fulltext, fetch_fulltext
from core.ingest.catalog import sync_catalog
from core.ingest.pipeline import ingest_all_feeds, ingest_gdelt_all
from core.ingest.ratelimit import DomainRateLimiter
from core.ingest.robots import RobotsCache
from core.ingest.rss import IngestStats
from core.net import build_client

log = logging.getLogger(__name__)


async def sync_catalog_job() -> None:
    maker = get_sessionmaker()
    async with maker() as session:
        stats = await sync_catalog(session)
        await session.commit()
    log.info("catalogo sincronizzato: %s", stats)


def _log_feed(slug: str, feed_url: str, stats: IngestStats) -> None:
    if stats.error:
        log.warning("%s %s: %s", slug, feed_url, stats.error)
    elif stats.created:
        log.info("%s: +%d articoli da %s", slug, stats.created, feed_url)


async def ingest_feeds_job() -> None:
    from core.refresh_state import tracking

    maker = get_sessionmaker()
    async with tracking("feed"), build_client() as client:
        # I feed in errore ripetuto restano in backoff (li ritenta il seed
        # o il giro successivo dopo la pausa): niente martellate inutili.
        await ingest_all_feeds(
            maker,
            client=client,
            limiter=DomainRateLimiter(),
            robots=RobotsCache(client),
            retry_failed=False,
            progress=_log_feed,
        )


async def ingest_gdelt_job() -> None:
    # Complemento di copertura per TUTTE le fonti: GDELT vede anche articoli
    # assenti dai feed RSS (il dedup per URL evita i doppi). Le richieste
    # viaggiano a batch di domini: una decina in tutto, non una per fonte.
    from core.refresh_state import tracking

    maker = get_sessionmaker()
    async with tracking("GDELT"), build_client() as client:
        created = await ingest_gdelt_all(
            maker, client=client, limiter=DomainRateLimiter()
        )
        for slug, n in created.items():
            if n:
                log.info("%s: +%d articoli via GDELT", slug, n)


async def fetch_fulltext_job(limit: int = 60) -> None:
    from core.refresh_state import tracking

    maker = get_sessionmaker()
    async with tracking("testi"), build_client() as client:
        limiter = DomainRateLimiter()
        robots = RobotsCache(client)
        from core import refresh_state

        async with maker() as session:
            articles = await articles_missing_fulltext(session, limit=limit)
            done = 0
            refresh_state.set_progress("testi", 0, len(articles))
            for i, article in enumerate(articles, start=1):
                refresh_state.set_progress("testi", i, len(articles))
                if await fetch_fulltext(
                    session, article, client=client, limiter=limiter, robots=robots
                ):
                    done += 1
            await session.commit()
    if done:
        log.info("testo integrale scaricato per %d articoli", done)

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


async def ingest_social_job() -> None:
    """Raccoglie gli articoli linkati dai canali social UFFICIALI delle testate.

    Solo piattaforme con API pubblica gratuita (Bluesky, Mastodon); solo
    post che linkano il dominio della testata; dedup per URL come sempre.
    Un canale che fallisce non ferma gli altri.
    """
    from sqlalchemy import select

    from core.ingest.catalog import load_catalog
    from core.ingest.social import (
        fetch_bluesky_items,
        fetch_mastodon_items,
        store_social_items,
        verified_handle,
    )
    from core.models import Source
    from core.refresh_state import tracking

    entries = [e for e in load_catalog() if e.enabled and e.social]
    if not entries:
        return
    maker = get_sessionmaker()
    async with tracking("social"), build_client() as client:
        from core import refresh_state

        limiter = DomainRateLimiter()
        refresh_state.set_progress("social", 0, len(entries))
        for indice, entry in enumerate(entries, start=1):
            refresh_state.set_progress("social", indice, len(entries))
            async with maker() as session:
                source = (
                    await session.execute(
                        select(Source).where(Source.slug == entry.slug)
                    )
                ).scalar_one_or_none()
                if source is None:
                    continue
                items = []
                handle = entry.social.get("bluesky")
                if handle:
                    if not verified_handle(handle, source):
                        # Mai un account non verificabile: su Bluesky l'handle
                        # DEVE essere il dominio della testata.
                        log.warning(
                            "%s: handle Bluesky %r non è il dominio della "
                            "testata: ignorato",
                            entry.slug, handle,
                        )
                    else:
                        try:
                            items += await fetch_bluesky_items(
                                client, limiter, handle
                            )
                        except Exception as exc:
                            log.warning(
                                "%s: Bluesky non raggiungibile ora: %s",
                                entry.slug, exc,
                            )
                mastodon = entry.social.get("mastodon")
                if mastodon:
                    try:
                        items += await fetch_mastodon_items(
                            client, limiter, mastodon
                        )
                    except Exception as exc:
                        log.warning(
                            "%s: Mastodon non raggiungibile ora: %s",
                            entry.slug, exc,
                        )
                created = await store_social_items(session, source, items)
                await session.commit()
                if created:
                    log.info("%s: +%d articoli dai canali social", entry.slug, created)


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

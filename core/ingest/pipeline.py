"""Orchestrazione della raccolta: rete in parallelo, database in sequenza.

Il collo di bottiglia della raccolta è l'attesa di rete (rate limit per host
+ latenza), non il lavoro locale: qui i feed vengono scaricati in parallelo
(limitati da un semaforo; il rate limiter per host resta rispettato) mentre
le scritture passano una alla volta da un lock condiviso — su SQLite c'è un
solo scrittore, su PostgreSQL il lock non costa nulla di percepibile.

GDELT viene interrogato a gruppi di domini (una richiesta per batch) e può
girare in parallelo alla raccolta RSS: host diversi, rate limit diversi.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.ingest.gdelt import (
    GdeltArticle,
    GdeltFormatError,
    error_text,
    fetch_domains_articles,
    match_source,
    store_gdelt_articles,
)
from core.ingest.ratelimit import DomainRateLimiter
from core.ingest.robots import RobotsCache
from core.ingest.rss import (
    FeedFetch,
    IngestStats,
    fetch_feed_content,
    in_backoff,
    store_feed,
)
from core.models import FeedState, Source

log = logging.getLogger(__name__)

FeedProgress = Callable[[str, str, IngestStats], None]
GdeltProgress = Callable[[str, int], None]

DEFAULT_CONCURRENCY = 10
GDELT_BATCH_SIZE = 6


async def _enabled_sources(session: AsyncSession) -> list[Source]:
    return list(
        (
            await session.execute(
                select(Source).where(Source.enabled).order_by(Source.id)
            )
        ).scalars()
    )


async def ingest_all_feeds(
    maker: async_sessionmaker[AsyncSession],
    *,
    client: httpx.AsyncClient,
    limiter: DomainRateLimiter,
    robots: RobotsCache,
    concurrency: int = DEFAULT_CONCURRENCY,
    max_feeds_per_source: int | None = None,
    retry_failed: bool = False,
    db_lock: asyncio.Lock | None = None,
    progress: FeedProgress | None = None,
) -> dict[str, int]:
    """Scarica tutti i feed abilitati in parallelo. Ritorna articoli per slug.

    Con `retry_failed` falso i feed in backoff (errori ripetuti di recente)
    vengono saltati in silenzio; il seed passa vero per provare tutto.
    """
    async with maker() as session:
        sources = await _enabled_sources(session)
        feed_urls = [
            url
            for src in sources
            for url in src.feed_urls[:max_feeds_per_source]
        ]
        states = {
            st.feed_url: st
            for st in (
                await session.execute(
                    select(FeedState).where(FeedState.feed_url.in_(feed_urls))
                )
            ).scalars()
        }

    jobs: list[tuple[Source, str, FeedState | None]] = []
    for src in sources:
        for url in src.feed_urls[:max_feeds_per_source]:
            state = states.get(url)
            if state is not None and not retry_failed and in_backoff(state):
                continue
            jobs.append((src, url, state))

    sem = asyncio.Semaphore(concurrency)

    async def run(
        src: Source, url: str, state: FeedState | None
    ) -> tuple[Source, str, FeedFetch]:
        async with sem:
            fetch = await fetch_feed_content(
                (state.resolved_url if state else None) or url,
                client=client,
                limiter=limiter,
                robots=robots,
                etag=state.etag if state else None,
                last_modified=state.last_modified if state else None,
                discovery_domain=src.domain,
            )
            fetch.requested_url = url
            return src, url, fetch

    lock = db_lock or asyncio.Lock()
    created: dict[str, int] = {}
    for task in asyncio.as_completed([run(*job) for job in jobs]):
        src, url, fetch = await task
        async with lock, maker() as session:
            merged = await session.get(Source, src.id)
            assert merged is not None
            stats = await store_feed(session, merged, url, fetch)
            await session.commit()
        created[src.slug] = created.get(src.slug, 0) + stats.created
        if progress is not None:
            progress(src.slug, url, stats)
    return created


def _chunk(seq: Sequence[Source], size: int) -> list[list[Source]]:
    return [list(seq[i : i + size]) for i in range(0, len(seq), size)]


async def ingest_gdelt_all(
    maker: async_sessionmaker[AsyncSession],
    *,
    client: httpx.AsyncClient,
    limiter: DomainRateLimiter,
    timespan: str = "24h",
    batch_size: int = GDELT_BATCH_SIZE,
    db_lock: asyncio.Lock | None = None,
    progress: GdeltProgress | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> dict[str, int]:
    """Complemento GDELT per tutte le fonti abilitate, a batch di domini.

    Le fonti SENZA feed (Reuters, AP, …) hanno una richiesta dedicata: GDELT
    è la loro unica copertura e non deve competere nel batch con le altre.
    I gruppi falliti (l'API GDELT sotto carico perde connessioni) vengono
    ritentati con un secondo passaggio a fine giro.
    """
    async with maker() as session:
        sources = [
            s for s in await _enabled_sources(session) if s.gdelt_domain
        ]

    solo = [s for s in sources if not s.feed_urls]
    complement = [s for s in sources if s.feed_urls]
    lock = db_lock or asyncio.Lock()
    created: dict[str, int] = {}

    async def store(source: Source, items: list[GdeltArticle], query: str) -> None:
        async with lock, maker() as session:
            merged = await session.get(Source, source.id)
            assert merged is not None
            n = await store_gdelt_articles(
                session, merged, items, query=query, timespan=timespan
            )
            await session.commit()
        created[source.slug] = created.get(source.slug, 0) + n
        if progress is not None:
            progress(source.slug, n)

    async def attempt(gruppo: list[Source]) -> bool:
        domains = [s.gdelt_domain for s in gruppo if s.gdelt_domain]
        query = (
            f"domain:{domains[0]}"
            if len(domains) == 1
            else "(" + " OR ".join(f"domain:{d}" for d in domains) + ")"
        )
        try:
            items = await fetch_domains_articles(
                client, limiter, domains,
                timespan=timespan,
                max_records=100 if len(domains) == 1 else 250,
                sleep=sleep,
            )
        except (httpx.HTTPError, GdeltFormatError) as exc:
            log.warning("GDELT %s: %s", ", ".join(domains), error_text(exc))
            return False
        by_source: dict[int, list[GdeltArticle]] = {}
        for item in items:
            matched = match_source(item, gruppo)
            if matched is not None:
                by_source.setdefault(matched.id, []).append(item)
        for source in gruppo:
            await store(source, by_source.get(source.id, []), query)
        return True

    gruppi = [[s] for s in solo] + _chunk(complement, batch_size)
    falliti = [g for g in gruppi if not await attempt(g)]
    if falliti:
        log.info("GDELT: secondo passaggio su %d gruppi falliti", len(falliti))
        for gruppo in falliti:
            await attempt(gruppo)
    return created

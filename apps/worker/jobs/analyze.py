"""Job di analisi: clustering incrementale, copertura, segnali settimanali."""

import logging

from sqlalchemy import select

from core.bias.aggregate import compute_weekly_signals
from core.cluster.coverage import compute_coverage
from core.cluster.incremental import cluster_pending
from core.db import get_sessionmaker
from core.models import Story
from core.net import build_client
from core.nlp.entities import assign_story_entities, link_entities_wikidata

log = logging.getLogger(__name__)


async def signals_job() -> None:
    maker = get_sessionmaker()
    async with maker() as session:
        await compute_weekly_signals(session)
        await session.commit()


async def cluster_job() -> None:
    maker = get_sessionmaker()
    async with maker() as session:
        stats = await cluster_pending(session)
        for story_id in stats.touched_story_ids:
            story = (
                await session.execute(select(Story).where(Story.id == story_id))
            ).scalar_one()
            await compute_coverage(session, story)
            await assign_story_entities(session, story)
        await session.commit()
    if stats.processed:
        log.info(
            "clustering: %d articoli (%d agganciati, %d nuove story, %d lampo)",
            stats.processed, stats.attached, stats.created, len(stats.new_flash),
        )


async def link_entities_job() -> None:
    """Collega a Wikidata le entità delle story recenti (best-effort)."""
    maker = get_sessionmaker()
    async with build_client() as client, maker() as session:
        linked = await link_entities_wikidata(session, client, limit=15)
        await session.commit()
    if linked:
        log.info("entità collegate a Wikidata: %d", linked)

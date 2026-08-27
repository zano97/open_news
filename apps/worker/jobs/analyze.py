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
from core.nlp.summarize import summarize_story

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


async def summarize_job() -> None:
    """Riassunti neutri per le story recenti multi-fonte (solo con ENABLE_LLM)."""
    from datetime import timedelta

    from core.config import get_settings
    from core.models import utcnow

    if not get_settings().enable_llm:
        return
    maker = get_sessionmaker()
    since = utcnow() - timedelta(hours=48)
    async with build_client(timeout=150) as client, maker() as session:
        stories = (
            (
                await session.execute(
                    select(Story)
                    .where(
                        Story.summary_neutral.is_(None),
                        Story.source_count >= 2,
                        Story.last_seen >= since,
                    )
                    .order_by(Story.source_count.desc())
                    .limit(10)
                )
            )
            .scalars()
            .all()
        )
        done = 0
        for story in stories:
            if await summarize_story(session, story, client=client):
                done += 1
        await session.commit()
    if done:
        log.info("riassunti neutri generati: %d", done)

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
from core.nlp.summarize import stories_needing_summary, summarize_story

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
    from core.config import get_settings

    if not get_settings().enable_llm:
        return
    maker = get_sessionmaker()
    async with build_client(timeout=200) as client, maker() as session:
        stories = await stories_needing_summary(session, limit=10)
        done = 0
        for story in stories:
            if await summarize_story(session, story, client=client):
                done += 1
        await session.commit()
    if done:
        log.info("riassunti neutri generati: %d", done)


async def refresh_settings_job() -> None:
    """Ricarica gli override del pannello admin (prevalgono sull'ambiente)."""
    from core.runtime_settings import load_overrides

    maker = get_sessionmaker()
    try:
        async with maker() as session:
            await load_overrides(session)
    except Exception:  # DB non pronto: si riprova al prossimo giro
        log.info("override impostazioni non caricati (DB non pronto)")


async def translate_titles_job() -> None:
    """Traduce i titoli neutri delle story recenti (solo se Argos è installato)."""
    from datetime import timedelta

    from core.models import utcnow
    from core.nlp.translate import get_translator, translate_story_title

    if get_translator() is None:
        return
    maker = get_sessionmaker()
    since = utcnow() - timedelta(hours=48)
    async with maker() as session:
        stories = (
            (
                await session.execute(
                    select(Story)
                    .where(Story.last_seen >= since)
                    .order_by(Story.last_seen.desc())
                    .limit(40)
                )
            )
            .scalars()
            .all()
        )
        added = 0
        for story in stories:
            added += await translate_story_title(session, story)
        await session.commit()
    if added:
        log.info("titoli neutri tradotti: %d", added)

"""Job di analisi: clustering incrementale e mappa di copertura."""

import logging

from sqlalchemy import select

from core.cluster.coverage import compute_coverage
from core.cluster.incremental import cluster_pending
from core.db import get_sessionmaker
from core.models import Story

log = logging.getLogger(__name__)


async def cluster_job() -> None:
    maker = get_sessionmaker()
    async with maker() as session:
        stats = await cluster_pending(session)
        for story_id in stats.touched_story_ids:
            story = (
                await session.execute(select(Story).where(Story.id == story_id))
            ).scalar_one()
            await compute_coverage(session, story)
        await session.commit()
    if stats.processed:
        log.info(
            "clustering: %d articoli (%d agganciati, %d nuove story, %d lampo)",
            stats.processed, stats.attached, stats.created, len(stats.new_flash),
        )

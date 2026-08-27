"""Ricerca dei vicini tra le story: nativa pgvector su PostgreSQL, in Python su SQLite.

Su PostgreSQL la distanza coseno usa l'operatore ``<=>`` e l'indice HNSW creato
dalla migrazione 0001; su SQLite (test) i candidati nella finestra temporale
vengono caricati e confrontati in Python: stessi risultati, volumi piccoli.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import Story
from core.nlp.embed import cosine


@dataclass(frozen=True)
class StoryMatch:
    story_id: int
    similarity: float


async def nearest_stories(
    session: AsyncSession,
    embedding: list[float],
    *,
    since: datetime,
    limit: int = 5,
) -> list[StoryMatch]:
    """Le story più simili (per centroide) viste dopo `since`, ordinate per similarità."""
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        rows = (
            await session.execute(
                text(
                    "SELECT id, 1 - (centroid <=> CAST(:emb AS vector)) AS sim "
                    "FROM stories "
                    "WHERE centroid IS NOT NULL AND last_seen >= :since "
                    "ORDER BY centroid <=> CAST(:emb AS vector) "
                    "LIMIT :lim"
                ),
                {"emb": str(embedding), "since": since, "lim": limit},
            )
        ).all()
        return [StoryMatch(int(r[0]), float(r[1])) for r in rows]

    stories = (
        (
            await session.execute(
                select(Story).where(Story.centroid.is_not(None), Story.last_seen >= since)
            )
        )
        .scalars()
        .all()
    )
    matches = [
        StoryMatch(story.id, cosine(embedding, story.centroid))
        for story in stories
        if story.centroid is not None
    ]
    matches.sort(key=lambda m: m.similarity, reverse=True)
    return matches[:limit]

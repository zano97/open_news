"""Mappa di copertura per story: chi la racconta (paese, lingua) e chi la ignora.

In questa fase si calcolano le distribuzioni per paese e lingua; i blind spot
per fonte e per fascia (livelli 2 e 4) arrivano da core/bias e vengono scritti
nello stesso record Coverage dal job settimanale.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import METHOD_VERSION
from core.models import Article, Coverage, Source, Story, utcnow
from core.provenance import record


async def compute_coverage(session: AsyncSession, story: Story) -> Coverage:
    rows = (
        await session.execute(
            select(Source.country, Article.language)
            .join(Source, Article.source_id == Source.id)
            .where(Article.story_id == story.id)
        )
    ).all()
    by_country: dict[str, int] = {}
    by_language: dict[str, int] = {}
    for country, language in rows:
        by_country[country] = by_country.get(country, 0) + 1
        lang = language or "?"
        by_language[lang] = by_language.get(lang, 0) + 1

    coverage = (
        await session.execute(select(Coverage).where(Coverage.story_id == story.id))
    ).scalar_one_or_none()
    if coverage is None:
        coverage = Coverage(story_id=story.id, method_version=METHOD_VERSION)
        session.add(coverage)
    coverage.by_country = by_country
    coverage.by_language = by_language
    coverage.method_version = METHOD_VERSION
    coverage.computed_at = utcnow()
    await session.flush()

    await record(
        session,
        entity_type="story",
        entity_id=story.id,
        field="coverage",
        method="coverage-count-v1",
        inputs={"articles": len(rows)},
    )
    return coverage

"""Livello 2 — Selezione: statistica pura, nessuna etichetta a priori.

Tre segnali, calcolati su finestra mobile e sempre datati:
- profilo di agenda: scostamento della distribuzione dei temi di una fonte
  dalla media delle fonti, con intervallo di confidenza bootstrap;
- mappa di co-copertura: PCA a 2 dimensioni della matrice fonte × story;
  gli assi sono emergenti e vanno letti tramite le story che li separano;
- blind spot: story molto coperte dalle altre fonti dello stesso paese ma
  ignorate da questa.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.bias.signals import write_signal
from core.config import get_settings
from core.models import Article, Coverage, Source, Story, utcnow
from core.nlp.topics import METHOD_NAME as TOPICS_METHOD
from core.nlp.topics import classify
from core.provenance import record

log = logging.getLogger(__name__)

AGENDA_METHOD = "agenda-deviation-v1"
COCOVERAGE_METHOD = "cocoverage-pca-v1"
BLINDSPOT_METHOD = "blindspot-country-v1"

MIN_ARTICLES_FOR_AGENDA = 10
BOOTSTRAP_SAMPLES = 200
BOOTSTRAP_SEED = 42
MIN_STORIES_FOR_MAP = 3


async def assign_story_topics(session: AsyncSession, since: datetime) -> int:
    """Classifica il tema delle story recenti (metodo keyword, dichiarato)."""
    stories = (
        (
            await session.execute(
                select(Story).where(Story.last_seen >= since)
            )
        )
        .scalars()
        .all()
    )
    updated = 0
    for story in stories:
        articles = (

                await session.execute(
                    select(Article.title, Article.language)
                    .where(Article.story_id == story.id)
                    .limit(8)
                )

        ).all()
        if not articles:
            continue
        languages = [a.language for a in articles if a.language]
        language = max(set(languages), key=languages.count) if languages else None
        text = story.title_neutral + ". " + ". ".join(a.title for a in articles)
        scores = classify(text, language)
        story.topics = [
            {"id": s.topic_id, "score": s.score} for s in scores[:3]
        ]
        story.topic = scores[0].topic_id if scores else None
        updated += 1
        await record(
            session,
            entity_type="story",
            entity_id=story.id,
            field="topic",
            method=TOPICS_METHOD,
            inputs={"language": language, "n_titles": len(articles)},
        )
    await session.flush()
    return updated


async def _topics_by_source(
    session: AsyncSession, since: datetime
) -> dict[int, list[str]]:
    rows = (
        await session.execute(
            select(Article.source_id, Story.topic)
            .join(Story, Article.story_id == Story.id)
            .where(Article.fetched_at >= since, Story.topic.is_not(None))
        )
    ).all()
    per_source: dict[int, list[str]] = {}
    for source_id, topic in rows:
        per_source.setdefault(source_id, []).append(topic)
    return per_source


def _shares(topics: list[str]) -> dict[str, float]:
    total = len(topics)
    counts: dict[str, int] = {}
    for t in topics:
        counts[t] = counts.get(t, 0) + 1
    return {t: c / total for t, c in counts.items()}


async def compute_agenda(session: AsyncSession, *, window_days: int = 30) -> int:
    """Scrive un segnale `agenda` per ogni fonte con abbastanza articoli."""
    until = utcnow()
    since = until - timedelta(days=window_days)
    per_source = await _topics_by_source(session, since)
    eligible = {
        sid: topics
        for sid, topics in per_source.items()
        if len(topics) >= MIN_ARTICLES_FOR_AGENDA
    }
    if len(eligible) < 2:
        log.info("agenda: fonti con dati sufficienti: %d (<2), salto", len(eligible))
        return 0

    all_topics = sorted({t for topics in eligible.values() for t in topics})
    share_by_source = {sid: _shares(topics) for sid, topics in eligible.items()}
    mean_share = {
        t: float(np.mean([share_by_source[sid].get(t, 0.0) for sid in eligible]))
        for t in all_topics
    }

    rng = np.random.default_rng(BOOTSTRAP_SEED)
    written = 0
    for sid, topics in eligible.items():
        n = len(topics)
        arr = np.array(topics)
        boot_devs: dict[str, list[float]] = {t: [] for t in all_topics}
        for _ in range(BOOTSTRAP_SAMPLES):
            sample = arr[rng.integers(0, n, n)]
            for t in all_topics:
                boot_devs[t].append(
                    float(np.mean(sample == t)) - mean_share[t]
                )
        value = {}
        for t in all_topics:
            devs = np.array(boot_devs[t])
            value[t] = {
                "share": round(share_by_source[sid].get(t, 0.0), 4),
                "mean": round(mean_share[t], 4),
                "deviation": round(share_by_source[sid].get(t, 0.0) - mean_share[t], 4),
                "ci_low": round(float(np.percentile(devs, 2.5)), 4),
                "ci_high": round(float(np.percentile(devs, 97.5)), 4),
            }
        await write_signal(
            session,
            source_id=sid,
            signal_type="agenda",
            period_start=since.date(),
            period_end=until.date(),
            value=value,
            n_articles=n,
            method=AGENDA_METHOD,
            inputs={
                "bootstrap_samples": BOOTSTRAP_SAMPLES,
                "seed": BOOTSTRAP_SEED,
                "topics_method": TOPICS_METHOD,
                "sources_in_mean": len(eligible),
            },
        )
        written += 1
    return written


@dataclass
class CocoverageResult:
    positions: dict[str, tuple[float, float]] = field(default_factory=dict)
    axis_stories: dict[str, list[dict[str, object]]] = field(default_factory=dict)
    n_stories: int = 0
    n_sources: int = 0
    explained_variance: tuple[float, float] = (0.0, 0.0)


async def cocoverage_map(
    session: AsyncSession, *, window_days: int = 30
) -> CocoverageResult:
    """PCA 2D della matrice fonte × story. Gli assi sono emergenti: vanno letti
    con le story a maggiore carico (axis_stories), mostrate accanto alla mappa."""
    since = utcnow() - timedelta(days=window_days)
    rows = (
        await session.execute(
            select(Article.source_id, Article.story_id)
            .join(Story, Article.story_id == Story.id)
            .where(Article.fetched_at >= since, Story.source_count >= 2)
            .distinct()
        )
    ).all()
    result = CocoverageResult()
    if not rows:
        return result

    coverage: dict[int, set[int]] = {}
    for source_id, story_id in rows:
        coverage.setdefault(source_id, set()).add(story_id)
    coverage = {
        sid: stories
        for sid, stories in coverage.items()
        if len(stories) >= MIN_STORIES_FOR_MAP
    }
    if len(coverage) < 3:
        return result

    story_ids = sorted({s for stories in coverage.values() for s in stories})
    source_ids = sorted(coverage)
    matrix = np.zeros((len(source_ids), len(story_ids)))
    story_index = {s: j for j, s in enumerate(story_ids)}
    for i, sid in enumerate(source_ids):
        for story_id in coverage[sid]:
            matrix[i, story_index[story_id]] = 1.0
    # Normalizzazione per riga (fonti più prolifiche non dominano)...
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    matrix = matrix / norms
    # ...e centratura per colonna prima della PCA.
    centered = matrix - matrix.mean(axis=0, keepdims=True)
    u, s, vt = np.linalg.svd(centered, full_matrices=False)
    positions = u[:, :2] * s[:2]
    total_var = float((s**2).sum()) or 1.0
    result.explained_variance = (
        round(float(s[0] ** 2 / total_var), 3),
        round(float(s[1] ** 2 / total_var), 3) if len(s) > 1 else 0.0,
    )

    slugs = {
        row.id: row.slug
        for row in (
            await session.execute(select(Source.id, Source.slug))
        ).all()
    }
    result.positions = {
        slugs[sid]: (round(float(positions[i, 0]), 4), round(float(positions[i, 1]), 4))
        for i, sid in enumerate(source_ids)
        if sid in slugs
    }
    result.n_stories = len(story_ids)
    result.n_sources = len(source_ids)

    titles = {
        row.id: row.title_neutral
        for row in (
            await session.execute(
                select(Story.id, Story.title_neutral).where(Story.id.in_(story_ids))
            )
        ).all()
    }
    for axis_idx, axis_name in ((0, "x"), (1, "y")):
        if axis_idx >= vt.shape[0]:
            break
        loadings = vt[axis_idx]
        order = np.argsort(loadings)
        for sign, key in ((1, f"{axis_name}_positive"), (-1, f"{axis_name}_negative")):
            picked = order[::-1][:10] if sign > 0 else order[:10]
            result.axis_stories[key] = [
                {
                    "story_id": story_ids[j],
                    "title": titles.get(story_ids[j], ""),
                    "loading": round(float(loadings[j]), 4),
                }
                for j in picked
                if abs(float(loadings[j])) > 1e-6
            ]
    return result


async def store_cocoverage(
    session: AsyncSession, *, window_days: int = 30
) -> int:
    until = utcnow()
    since = until - timedelta(days=window_days)
    result = await cocoverage_map(session, window_days=window_days)
    if not result.positions:
        return 0
    ids = {
        row.slug: row.id
        for row in (await session.execute(select(Source.id, Source.slug))).all()
    }
    written = 0
    for slug, (x, y) in result.positions.items():
        await write_signal(
            session,
            source_id=ids[slug],
            signal_type="cocoverage",
            period_start=since.date(),
            period_end=until.date(),
            value={"x": x, "y": y},
            n_articles=result.n_stories,
            method=COCOVERAGE_METHOD,
            inputs={
                "n_sources": result.n_sources,
                "n_stories": result.n_stories,
                "explained_variance": list(result.explained_variance),
            },
        )
        written += 1
    return written


async def compute_blindspots(
    session: AsyncSession, *, window_days: int = 30
) -> int:
    """Per ogni fonte: story molto coperte nel suo paese ma ignorate da lei.

    Aggiorna anche Coverage.blindspot_for a livello di story (paesi con
    almeno 3 fonti attive che l'hanno ignorata mentre >=5 fonti la coprivano).
    """
    settings = get_settings()
    threshold = settings.blindspot_coverage_pct
    until = utcnow()
    since = until - timedelta(days=window_days)

    sources = {
        s.id: s
        for s in (
            await session.execute(select(Source).where(Source.enabled))
        ).scalars()
    }
    rows = (
        await session.execute(
            select(Article.source_id, Article.story_id)
            .join(Story, Article.story_id == Story.id)
            .where(Article.fetched_at >= since, Article.story_id.is_not(None))
            .distinct()
        )
    ).all()
    story_sources: dict[int, set[int]] = {}
    active_by_country: dict[str, set[int]] = {}
    for source_id, story_id in rows:
        if source_id not in sources:
            continue
        story_sources.setdefault(story_id, set()).add(source_id)
        active_by_country.setdefault(sources[source_id].country, set()).add(source_id)

    written = 0
    for sid, source in sources.items():
        country_active = active_by_country.get(source.country, set())
        if len(country_active) < 3 or sid not in country_active:
            continue
        others = country_active - {sid}
        missed: list[int] = []
        for story_id, covering in story_sources.items():
            covering_same_country = covering & others
            needed = max(2, round(threshold * len(others)))
            if sid not in covering and len(covering_same_country) >= needed:
                missed.append(story_id)
        await write_signal(
            session,
            source_id=sid,
            signal_type="blindspot",
            period_start=since.date(),
            period_end=until.date(),
            value={
                "story_ids": sorted(missed)[-50:],
                "count": len(missed),
                "threshold": threshold,
                "country": source.country,
                "peers": len(others),
            },
            n_articles=len(story_sources),
            method=BLINDSPOT_METHOD,
            inputs={"threshold": threshold, "country": source.country},
        )
        written += 1

    # Blind spot a livello di story: fasce/paesi che l'hanno ignorata.
    for story_id, covering in story_sources.items():
        if len(covering) < 5:
            continue
        ignored_by: list[dict[str, object]] = []
        covering_countries = {sources[sid].country for sid in covering}
        for country, active in active_by_country.items():
            if len(active) >= 3 and country not in covering_countries:
                ignored_by.append(
                    {"group": country, "kind": "country", "threshold": threshold}
                )
        if not ignored_by:
            continue
        coverage = (
            await session.execute(
                select(Coverage).where(Coverage.story_id == story_id)
            )
        ).scalar_one_or_none()
        if coverage is not None:
            coverage.blindspot_for = ignored_by
            coverage.computed_at = datetime.now(UTC)
    await session.flush()
    return written

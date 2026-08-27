"""Pagine HTML (Jinja2 + HTMX)."""

import math
from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.signal_views import shape_signals
from apps.api.svg import cocoverage_scatter_svg, coverage_bar_svg, ownership_graph_svg
from apps.api.templating import templates
from core.bias.selection import cocoverage_map
from core.bias.structure import source_profile
from core.db import get_session
from core.models import Article, BiasSignal, Coverage, Owner, Ownership, Source, Story, utcnow
from core.nlp.topics import load_topics
from core.provenance import for_entity

router = APIRouter()


async def _owners_by_source(
    session: AsyncSession, source_ids: list[int]
) -> dict[int, str]:
    """Primo proprietario registrato per fonte (per la stampigliatura piccola)."""
    if not source_ids:
        return {}
    rows = (
        await session.execute(
            select(Ownership.source_id, Owner.name)
            .join(Owner, Ownership.owner_id == Owner.id)
            .where(Ownership.source_id.in_(source_ids))
            .order_by(Owner.name)
        )
    ).all()
    owners: dict[int, str] = {}
    for source_id, name in rows:
        owners.setdefault(source_id, name)
    return owners


async def _coverages_for(
    session: AsyncSession, story_ids: list[int]
) -> dict[int, Coverage]:
    if not story_ids:
        return {}
    rows = (
        await session.execute(select(Coverage).where(Coverage.story_id.in_(story_ids)))
    ).scalars()
    return {c.story_id: c for c in rows}


async def _cocoverage_positions(
    session: AsyncSession,
) -> dict[int, tuple[float, float]]:
    """Ultima posizione di co-copertura per fonte (per la scelta di versioni diverse)."""
    rows = (
        (
            await session.execute(
                select(BiasSignal)
                .where(BiasSignal.signal_type == "cocoverage")
                .order_by(BiasSignal.period_end.desc())
            )
        )
        .scalars()
        .all()
    )
    positions: dict[int, tuple[float, float]] = {}
    for signal in rows:
        if signal.source_id not in positions and isinstance(signal.value, dict):
            positions[signal.source_id] = (
                float(signal.value.get("x", 0)),
                float(signal.value.get("y", 0)),
            )
    return positions


def diverse_articles(
    articles: list[Article],
    positions: dict[int, tuple[float, float]],
    k: int = 3,
) -> list[Article]:
    """Fino a k articoli di fonti diverse, scelti per massimizzare la diversità.

    Con le posizioni di co-copertura (livello 2) si massimizza la distanza
    reciproca; senza, si privilegiano paesi e fonti diverse. Metodo dichiarato
    nella pagina /metodo.
    """
    per_source: dict[int, Article] = {}
    for article in articles:
        per_source.setdefault(article.source_id, article)
    candidates = list(per_source.values())
    if len(candidates) <= k:
        return candidates

    def dist(a: Article, b: Article) -> float:
        pa, pb = positions.get(a.source_id), positions.get(b.source_id)
        if pa is not None and pb is not None:
            return math.hypot(pa[0] - pb[0], pa[1] - pb[1])
        score = 0.0
        if a.source.country != b.source.country:
            score += 1.0
        if a.source.language != b.source.language:
            score += 0.5
        return score

    chosen = [candidates[0]]
    while len(chosen) < k:
        best = max(
            (c for c in candidates if c not in chosen),
            key=lambda c: min(dist(c, ch) for ch in chosen),
        )
        chosen.append(best)
    return chosen


async def masthead_context(session: AsyncSession) -> dict[str, Any]:
    """Numeri del colonnino di testata, presenti su ogni pagina."""
    source_count = (
        await session.execute(select(func.count()).select_from(Source).where(Source.enabled))
    ).scalar_one()
    story_count = (
        await session.execute(select(func.count()).select_from(Story))
    ).scalar_one()
    last_update = (
        await session.execute(select(func.max(Article.fetched_at)))
    ).scalar_one_or_none()
    return {
        "source_count": source_count,
        "story_count": story_count,
        "last_update": last_update,
    }


@router.get("/", response_class=HTMLResponse)
async def index(
    request: Request, session: Annotated[AsyncSession, Depends(get_session)]
) -> HTMLResponse:
    stories = (
        (
            await session.execute(
                select(Story)
                .order_by(Story.source_count.desc(), Story.last_seen.desc())
                .limit(36)
            )
        )
        .scalars()
        .all()
    )
    coverages = await _coverages_for(session, [s.id for s in stories])
    topic_labels = {t.id: t.label_it for t in load_topics()}
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            **await masthead_context(session),
            "stories": stories,
            "coverages": coverages,
            "topic_labels": topic_labels,
        },
    )


@router.get("/storia/{story_id}", response_class=HTMLResponse)
async def storia(
    request: Request,
    story_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    story = (
        await session.execute(select(Story).where(Story.id == story_id))
    ).scalar_one_or_none()
    if story is None:
        raise HTTPException(status_code=404, detail="story sconosciuta")
    coverage = (
        await session.execute(select(Coverage).where(Coverage.story_id == story.id))
    ).scalar_one_or_none()
    owners = await _owners_by_source(session, [a.source_id for a in story.articles])
    timeline = sorted(
        story.articles, key=lambda a: (a.published_at or a.fetched_at)
    )
    paesi_svg = None
    if coverage and coverage.by_country:
        paesi_svg = coverage_bar_svg(
            coverage.by_country,
            label=f"Copertura per paese della story {story.id}",
        )
    provenances = await for_entity(session, "story", story.id)
    topic_labels = {t.id: t.label_it for t in load_topics()}
    return templates.TemplateResponse(
        request,
        "storia.html",
        {
            **await masthead_context(session),
            "story": story,
            "coverage": coverage,
            "owners": owners,
            "timeline": timeline,
            "paesi_svg": paesi_svg,
            "provenances": provenances,
            "topic_labels": topic_labels,
        },
    )


@router.get("/lampo", response_class=HTMLResponse)
async def lampo(
    request: Request, session: Annotated[AsyncSession, Depends(get_session)]
) -> HTMLResponse:
    since = utcnow() - timedelta(hours=12)
    stories = (
        (
            await session.execute(
                select(Story)
                .where(Story.is_flash, Story.last_seen >= since)
                .order_by(Story.last_seen.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    positions = await _cocoverage_positions(session)
    coverages = await _coverages_for(session, [s.id for s in stories])
    all_source_ids = sorted(
        {a.source_id for s in stories for a in s.articles}
    )
    owners = await _owners_by_source(session, all_source_ids)
    schede = []
    for story in stories:
        countries = {a.source.country for a in story.articles}
        schede.append(
            {
                "story": story,
                "countries": len(countries),
                "versions": diverse_articles(story.articles, positions),
                "coverage": coverages.get(story.id),
            }
        )
    from core.config import get_settings

    settings = get_settings()
    return templates.TemplateResponse(
        request,
        "lampo.html",
        {
            **await masthead_context(session),
            "schede": schede,
            "owners": owners,
            "flash_min": settings.flash_min_sources,
            "flash_window": settings.flash_window_hours,
        },
    )


@router.get("/fonti", response_class=HTMLResponse)
async def fonti(
    request: Request, session: Annotated[AsyncSession, Depends(get_session)]
) -> HTMLResponse:
    sources = (
        (await session.execute(select(Source).order_by(Source.region, Source.name)))
        .scalars()
        .all()
    )
    regioni: dict[str, list[Source]] = {"italy": [], "europe": [], "world": []}
    for src in sources:
        regioni.setdefault(src.region, []).append(src)
    return templates.TemplateResponse(
        request,
        "fonti.html",
        {**await masthead_context(session), "regioni": regioni},
    )


@router.get("/fonte/{slug}", response_class=HTMLResponse)
async def fonte(
    request: Request,
    slug: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    profile = await source_profile(session, slug)
    if profile is None:
        raise HTTPException(status_code=404, detail="fonte sconosciuta")
    article_count = (
        await session.execute(
            select(func.count()).select_from(Article).where(
                Article.source_id == profile.source.id
            )
        )
    ).scalar_one()
    provenances = await for_entity(session, "source", profile.source.id)
    topic_labels = {t.id: t.label_it for t in load_topics()}
    signal_views = shape_signals(profile.signals, topic_labels)

    mappa_svg = None
    if "cocoverage" in signal_views:
        mappa = await cocoverage_map(session)
        if mappa.positions:
            nomi = {
                s.slug: s.name
                for s in (await session.execute(select(Source))).scalars()
            }
            mappa_svg = cocoverage_scatter_svg(
                mappa.positions, highlight=slug, names=nomi
            )

    tono_svg = None
    if "tone" in signal_views:
        tono_svg = coverage_bar_svg(
            signal_views["tone"].data["distribution"],
            label=f"Distribuzione del tono dei titoli di {profile.source.name}",
        )

    return templates.TemplateResponse(
        request,
        "fonte.html",
        {
            **await masthead_context(session),
            "profile": profile,
            "article_count": article_count,
            "grafo_svg": ownership_graph_svg(profile),
            "provenances": provenances,
            "signal_views": signal_views,
            "mappa_svg": mappa_svg,
            "tono_svg": tono_svg,
        },
    )


@router.get("/mappa", response_class=HTMLResponse)
async def mappa(
    request: Request, session: Annotated[AsyncSession, Depends(get_session)]
) -> HTMLResponse:
    result = await cocoverage_map(session)
    nomi = {
        s.slug: s.name for s in (await session.execute(select(Source))).scalars()
    }
    svg = cocoverage_scatter_svg(result.positions, names=nomi)
    return templates.TemplateResponse(
        request,
        "mappa.html",
        {
            **await masthead_context(session),
            "result": result,
            "mappa_svg": svg,
        },
    )

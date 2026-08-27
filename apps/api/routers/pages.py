"""Pagine HTML (Jinja2 + HTMX)."""

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
from core.models import Article, Source, Story
from core.nlp.topics import load_topics
from core.provenance import for_entity

router = APIRouter()


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
                select(Story).order_by(Story.last_seen.desc()).limit(36)
            )
        )
        .scalars()
        .all()
    )
    return templates.TemplateResponse(
        request,
        "index.html",
        {**await masthead_context(session), "stories": stories},
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

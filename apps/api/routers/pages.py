"""Pagine HTML (Jinja2 + HTMX). In Fase 0: solo homepage minimale."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.templating import templates
from core.db import get_session
from core.models import Source, Story

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def index(
    request: Request, session: Annotated[AsyncSession, Depends(get_session)]
) -> HTMLResponse:
    source_count = (
        await session.execute(select(func.count()).select_from(Source).where(Source.enabled))
    ).scalar_one()
    story_count = (
        await session.execute(select(func.count()).select_from(Story))
    ).scalar_one()
    stories = (
        (
            await session.execute(
                select(Story).order_by(Story.last_seen.desc()).limit(30)
            )
        )
        .scalars()
        .all()
    )
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "source_count": source_count,
            "story_count": story_count,
            "stories": stories,
        },
    )

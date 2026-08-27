"""Pagine /metodo e /dati: la metodologia pubblica e gli export aperti."""

from functools import lru_cache
from typing import Annotated

import markdown
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.routers.pages import masthead_context
from apps.api.templating import templates
from core.config import BASE_DIR
from core.db import get_session

router = APIRouter()

METHODOLOGY_PATH = BASE_DIR / "docs" / "METHODOLOGY.md"


@lru_cache(maxsize=1)
def _methodology_html(mtime: float) -> str:
    """Render del markdown, cache invalidata dal mtime del file."""
    del mtime
    text = METHODOLOGY_PATH.read_text(encoding="utf-8")
    return markdown.markdown(text, extensions=["tables", "toc"])


@router.get("/metodo", response_class=HTMLResponse)
async def metodo(
    request: Request, session: Annotated[AsyncSession, Depends(get_session)]
) -> HTMLResponse:
    html = _methodology_html(METHODOLOGY_PATH.stat().st_mtime)
    return templates.TemplateResponse(
        request,
        "metodo.html",
        {**await masthead_context(session), "contenuto": html},
    )


@router.get("/dati", response_class=HTMLResponse)
async def dati(
    request: Request, session: Annotated[AsyncSession, Depends(get_session)]
) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "dati.html", {**await masthead_context(session)}
    )

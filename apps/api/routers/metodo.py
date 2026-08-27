"""Pagine /metodo e /dati: la metodologia pubblica e gli export aperti.

La metodologia è un documento lungo: esiste in italiano (originale) e in
inglese. Per le altre lingue dell'interfaccia si serve la versione inglese
con una nota di cortesia; le traduzioni arrivano via pull request.
"""

from functools import lru_cache
from pathlib import Path
from typing import Annotated

import markdown
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.routers.pages import page_context, request_locale
from apps.api.templating import templates
from core.config import BASE_DIR
from core.db import get_session
from core.i18n import LOCALE_NAMES

router = APIRouter()

DOCS_DIR = BASE_DIR / "docs"
METHODOLOGY_BY_LOCALE = {
    "it": DOCS_DIR / "METHODOLOGY.md",
    "en": DOCS_DIR / "METHODOLOGY.en.md",
}


def _methodology_path(locale: str) -> tuple[Path, bool]:
    """(percorso, è_fallback): il documento nella lingua richiesta o in inglese."""
    path = METHODOLOGY_BY_LOCALE.get(locale)
    if path is not None and path.exists():
        return path, False
    english = METHODOLOGY_BY_LOCALE["en"]
    if english.exists():
        return english, locale != "en"
    return METHODOLOGY_BY_LOCALE["it"], locale != "it"


@lru_cache(maxsize=8)
def _methodology_html(path_str: str, mtime: float) -> str:
    """Render del markdown, cache invalidata dal mtime del file."""
    del mtime
    text = Path(path_str).read_text(encoding="utf-8")
    return markdown.markdown(text, extensions=["tables", "toc"])


@router.get("/metodo", response_class=HTMLResponse)
async def metodo(
    request: Request, session: Annotated[AsyncSession, Depends(get_session)]
) -> HTMLResponse:
    locale = request_locale(request)
    path, is_fallback = _methodology_path(locale)
    html = _methodology_html(str(path), path.stat().st_mtime)
    return templates.TemplateResponse(
        request,
        "metodo.html",
        {
            **await page_context(request, session),
            "contenuto": html,
            "fallback_lingua": LOCALE_NAMES.get(locale, locale) if is_fallback else None,
        },
    )


@router.get("/dati", response_class=HTMLResponse)
async def dati(
    request: Request, session: Annotated[AsyncSession, Depends(get_session)]
) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "dati.html", {**await page_context(request, session)}
    )

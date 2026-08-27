"""Pannello /impostazioni: parametri operativi modificabili dall'admin.

Accesso: solo annotatori con `is_admin` (il primo profilo registrato).
Le modifiche finiscono in `app_settings`, prevalgono sulle variabili
d'ambiente e vengono applicate a caldo; il worker le ricarica entro 5 minuti.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.routers.annotate import current_annotator
from apps.api.routers.pages import page_context, request_locale
from apps.api.templating import templates
from core.config import get_settings
from core.db import get_session
from core.i18n import make_translator
from core.models import AnnotatorProfile, Story
from core.net import build_client
from core.nlp.summarize import (
    check_ollama,
    stories_needing_summary,
    summarize_story,
)
from core.runtime_settings import (
    EDITABLE,
    current_values,
    last_update,
    save_overrides,
)

router = APIRouter(prefix="/impostazioni")


async def _llm_panel(session: AsyncSession) -> dict[str, object]:
    """Diagnosi in diretta del generatore di riassunti, per il pannello."""
    status = None
    if get_settings().enable_llm:
        async with build_client(timeout=6) as client:
            status = await check_ollama(client)
    fatti = (
        await session.execute(
            select(func.count())
            .select_from(Story)
            .where(Story.summary_neutral.is_not(None))
        )
    ).scalar_one()
    in_attesa = len(await stories_needing_summary(session, limit=50))
    return {"llm_status": status, "riassunti_fatti": fatti, "riassunti_attesa": in_attesa}


async def _render(
    request: Request,
    session: AsyncSession,
    *,
    errors: dict[str, str],
    saved: bool,
    status_code: int = 200,
    esito_riassunti: int | None = None,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "impostazioni.html",
        {
            **await page_context(request, session),
            "specs": EDITABLE,
            "values": current_values(),
            "errors": errors,
            "saved": saved,
            "ultima": await last_update(session),
            "esito_riassunti": esito_riassunti,
            **await _llm_panel(session),
        },
        status_code=status_code,
    )


def _forbidden(request: Request, annotator: AnnotatorProfile | None) -> HTMLResponse:
    t = make_translator(request_locale(request))
    corpo = t("imp.solo_admin")
    link = f'<p><a href="/annota/entra">{t("annota.entra")}</a></p>' if annotator is None else ""
    return HTMLResponse(
        f'<main class="modulo"><p>{corpo}</p>{link}</main>', status_code=403
    )


@router.get("", response_class=HTMLResponse, response_model=None)
async def impostazioni(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    annotator: Annotated[AnnotatorProfile | None, Depends(current_annotator)],
    salvate: int = 0,
    riassunti: int | None = None,
) -> HTMLResponse:
    if annotator is None or not annotator.is_admin:
        return _forbidden(request, annotator)
    return await _render(
        request, session, errors={}, saved=bool(salvate), esito_riassunti=riassunti
    )


@router.post("/riassunti-prova", response_model=None)
async def riassunti_prova(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    annotator: Annotated[AnnotatorProfile | None, Depends(current_annotator)],
) -> HTMLResponse | RedirectResponse:
    """Genera subito fino a 3 riassunti, senza aspettare il worker."""
    if annotator is None or not annotator.is_admin:
        return _forbidden(request, annotator)
    done = 0
    if get_settings().enable_llm:
        stories = await stories_needing_summary(session, limit=3)
        async with build_client(timeout=200) as client:
            for story in stories:
                if await summarize_story(session, story, client=client):
                    done += 1
        await session.commit()
    return RedirectResponse(f"/impostazioni?riassunti={done}", status_code=303)


@router.post("", response_class=HTMLResponse, response_model=None)
async def salva_impostazioni(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    annotator: Annotated[AnnotatorProfile | None, Depends(current_annotator)],
) -> HTMLResponse | RedirectResponse:
    if annotator is None or not annotator.is_admin:
        return _forbidden(request, annotator)
    form = {str(k): str(v) for k, v in (await request.form()).items()}
    raw_errors = await save_overrides(session, form, updated_by=annotator.username)
    await session.commit()
    if raw_errors:
        t = make_translator(request_locale(request))
        errors = {
            key: t(exc.reason_key, **exc.params) for key, exc in raw_errors.items()
        }
        return await _render(
            request, session, errors=errors, saved=False, status_code=422
        )
    return RedirectResponse("/impostazioni?salvate=1", status_code=303)

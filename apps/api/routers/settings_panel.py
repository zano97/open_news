"""Pannello /impostazioni: parametri operativi modificabili dall'admin.

Accesso: solo annotatori con `is_admin` (il primo profilo registrato).
Le modifiche finiscono in `app_settings`, prevalgono sulle variabili
d'ambiente e vengono applicate a caldo; il worker le ricarica entro 5 minuti.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.routers.annotate import current_annotator
from apps.api.routers.pages import page_context, request_locale
from apps.api.templating import templates
from core.db import get_session
from core.i18n import make_translator
from core.models import AnnotatorProfile
from core.runtime_settings import (
    EDITABLE,
    current_values,
    last_update,
    save_overrides,
)

router = APIRouter(prefix="/impostazioni")


async def _render(
    request: Request,
    session: AsyncSession,
    *,
    errors: dict[str, str],
    saved: bool,
    status_code: int = 200,
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
) -> HTMLResponse:
    if annotator is None or not annotator.is_admin:
        return _forbidden(request, annotator)
    return await _render(request, session, errors={}, saved=bool(salvate))


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

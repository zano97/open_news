"""Annotazione cieca (livello 4): registrazione locale, scheda, salvataggio.

Cecità: la scheda mostra solo titolo e snippet — mai testata, URL o immagine.
Campionamento: si privilegia la fonte con meno annotazioni dell'annotatore
(campionamento stratificato per fonte), poi un articolo casuale non ancora
annotato da lui.
"""

import random
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.routers.pages import masthead_context
from apps.api.templating import templates
from core.auth import (
    SESSION_COOKIE,
    hash_password,
    make_session_token,
    read_session_token,
    verify_password,
)
from core.db import get_session
from core.models import Annotation, AnnotatorProfile, Article, Source

router = APIRouter(prefix="/annota")

AXIS_VALUES = {"-2", "-1", "0", "1", "2", "na"}


async def current_annotator(
    request: Request, session: Annotated[AsyncSession, Depends(get_session)]
) -> AnnotatorProfile | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    annotator_id = read_session_token(token)
    if annotator_id is None:
        return None
    return (
        await session.execute(
            select(AnnotatorProfile).where(AnnotatorProfile.id == annotator_id)
        )
    ).scalar_one_or_none()


def _set_session(response: Response, annotator_id: int) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        make_session_token(annotator_id),
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )


@router.get("/registrati", response_class=HTMLResponse)
async def registrati_form(
    request: Request, session: Annotated[AsyncSession, Depends(get_session)]
) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "annota_registrati.html", {**await masthead_context(session)}
    )


@router.post("/registrati")
async def registrati(
    session: Annotated[AsyncSession, Depends(get_session)],
    username: Annotated[str, Form(min_length=3, max_length=60)],
    password: Annotated[str, Form(min_length=8)],
    display_name: Annotated[str, Form()] = "",
    self_axis_economic: Annotated[float, Form(ge=-2, le=2)] = 0.0,
    self_axis_cultural: Annotated[float, Form(ge=-2, le=2)] = 0.0,
) -> RedirectResponse:
    existing = (
        await session.execute(
            select(AnnotatorProfile).where(AnnotatorProfile.username == username)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="nome utente già in uso")
    annotator = AnnotatorProfile(
        username=username,
        password_hash=hash_password(password),
        display_name=display_name or username,
        self_axis_economic=self_axis_economic,
        self_axis_cultural=self_axis_cultural,
    )
    session.add(annotator)
    await session.commit()
    response = RedirectResponse("/annota", status_code=303)
    _set_session(response, annotator.id)
    return response


@router.get("/entra", response_class=HTMLResponse)
async def entra_form(
    request: Request, session: Annotated[AsyncSession, Depends(get_session)]
) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "annota_entra.html", {**await masthead_context(session)}
    )


@router.post("/entra")
async def entra(
    session: Annotated[AsyncSession, Depends(get_session)],
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
) -> RedirectResponse:
    annotator = (
        await session.execute(
            select(AnnotatorProfile).where(AnnotatorProfile.username == username)
        )
    ).scalar_one_or_none()
    if annotator is None or not verify_password(password, annotator.password_hash):
        raise HTTPException(status_code=401, detail="credenziali non valide")
    response = RedirectResponse("/annota", status_code=303)
    _set_session(response, annotator.id)
    return response


@router.post("/esci")
async def esci() -> RedirectResponse:
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response


async def _pick_article(
    session: AsyncSession, annotator: AnnotatorProfile
) -> Article | None:
    """Fonte meno annotata dall'annotatore, poi articolo casuale non suo."""
    annotated = (
        select(Annotation.article_id)
        .where(Annotation.annotator_id == annotator.id)
        .subquery()
    )
    per_source = (
        await session.execute(
            select(Article.source_id, func.count(Article.id))
            .join(Source, Article.source_id == Source.id)
            .where(Source.enabled, Article.id.not_in(select(annotated.c.article_id)))
            .group_by(Article.source_id)
        )
    ).all()
    if not per_source:
        return None
    mine: dict[int, int] = {
        row[0]: row[1]
        for row in (
            await session.execute(
                select(Article.source_id, func.count(Annotation.id))
                .join(Annotation, Annotation.article_id == Article.id)
                .where(Annotation.annotator_id == annotator.id)
                .group_by(Article.source_id)
            )
        ).all()
    }
    source_id = min(per_source, key=lambda row: (mine.get(row[0], 0), random.random()))[0]
    candidates = (
        (
            await session.execute(
                select(Article.id)
                .where(
                    Article.source_id == source_id,
                    Article.id.not_in(select(annotated.c.article_id)),
                )
                .order_by(Article.id.desc())
                .limit(200)
            )
        )
        .scalars()
        .all()
    )
    chosen = random.choice(list(candidates))
    return (
        await session.execute(select(Article).where(Article.id == chosen))
    ).scalar_one()


@router.get("", response_class=HTMLResponse, response_model=None)
async def annota(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    annotator: Annotated[AnnotatorProfile | None, Depends(current_annotator)],
) -> HTMLResponse | RedirectResponse:
    if annotator is None:
        return RedirectResponse("/annota/entra", status_code=303)
    article = await _pick_article(session, annotator)
    my_count = (
        await session.execute(
            select(func.count(func.distinct(Annotation.article_id))).where(
                Annotation.annotator_id == annotator.id
            )
        )
    ).scalar_one()
    return templates.TemplateResponse(
        request,
        "annota.html",
        {
            **await masthead_context(session),
            "annotator": annotator,
            "article": article,
            "my_count": my_count,
        },
    )


@router.post("")
async def salva(
    session: Annotated[AsyncSession, Depends(get_session)],
    annotator: Annotated[AnnotatorProfile | None, Depends(current_annotator)],
    article_id: Annotated[int, Form()],
    economic: Annotated[str, Form()],
    cultural: Annotated[str, Form()],
    confidence: Annotated[int, Form(ge=1, le=3)] = 2,
) -> RedirectResponse:
    if annotator is None:
        return RedirectResponse("/annota/entra", status_code=303)
    if economic not in AXIS_VALUES or cultural not in AXIS_VALUES:
        raise HTTPException(status_code=422, detail="valore fuori scala")
    article = (
        await session.execute(select(Article).where(Article.id == article_id))
    ).scalar_one_or_none()
    if article is None:
        raise HTTPException(status_code=404, detail="articolo sconosciuto")

    for axis, raw in (("economic", economic), ("cultural", cultural)):
        existing = (
            await session.execute(
                select(Annotation).where(
                    Annotation.article_id == article_id,
                    Annotation.annotator_id == annotator.id,
                    Annotation.axis == axis,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            existing = Annotation(
                article_id=article_id, annotator_id=annotator.id, axis=axis
            )
            session.add(existing)
        existing.not_applicable = raw == "na"
        existing.value = None if raw == "na" else int(raw)
        existing.confidence = confidence
    await session.commit()
    return RedirectResponse("/annota", status_code=303)

"""Export aperti (/dati): dati derivati in CC BY-SA 4.0.

L'export delle annotazioni è anonimizzato: l'annotatore compare come "a{id}"
con il suo orientamento dichiarato (necessario per riprodurre i calcoli),
mai con nome utente.
"""

import csv
import io
import json
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import METHOD_VERSION
from core.db import get_session
from core.models import (
    Annotation,
    AnnotatorProfile,
    Article,
    BiasSignal,
    Coverage,
    Source,
    Story,
)

router = APIRouter(prefix="/dati")

_LICENZA = (
    "# Open News — dati derivati, licenza CC BY-SA 4.0 "
    "(https://creativecommons.org/licenses/by-sa/4.0/deed.it). "
    f"Metodo v.{METHOD_VERSION}: vedi /metodo.\n"
)


def _csv_response(filename: str, header: list[str], rows: list[list[object]]) -> Response:
    buffer = io.StringIO()
    buffer.write(_LICENZA)
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/annotazioni.csv")
async def annotazioni_csv(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    rows = (
        await session.execute(
            select(Annotation, AnnotatorProfile, Article.source_id)
            .join(AnnotatorProfile, Annotation.annotator_id == AnnotatorProfile.id)
            .join(Article, Annotation.article_id == Article.id)
            .order_by(Annotation.id)
        )
    ).all()
    return _csv_response(
        "annotazioni.csv",
        [
            "article_id", "source_id", "axis", "value", "not_applicable",
            "confidence", "annotator", "annotator_declared_economic",
            "annotator_declared_cultural", "created_at",
        ],
        [
            [
                a.article_id, source_id, a.axis,
                a.value if a.value is not None else "",
                int(a.not_applicable), a.confidence, f"a{p.id}",
                p.self_axis_economic, p.self_axis_cultural,
                a.created_at.isoformat(),
            ]
            for a, p, source_id in rows
        ],
    )


@router.get("/story.csv")
async def story_csv(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    stories = (await session.execute(select(Story).order_by(Story.id))).scalars().all()
    return _csv_response(
        "story.csv",
        [
            "story_id", "title_neutral", "title_method", "topic", "first_seen",
            "last_seen", "article_count", "source_count", "is_flash",
        ],
        [
            [
                s.id, s.title_neutral, s.title_method, s.topic or "",
                s.first_seen.isoformat(), s.last_seen.isoformat(),
                s.article_count, s.source_count, int(s.is_flash),
            ]
            for s in stories
        ],
    )


@router.get("/coperture.csv")
async def coperture_csv(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    rows = (
        await session.execute(select(Coverage).order_by(Coverage.story_id))
    ).scalars().all()
    return _csv_response(
        "coperture.csv",
        ["story_id", "by_country", "by_language", "blindspot_for", "computed_at"],
        [
            [
                c.story_id, json.dumps(c.by_country, ensure_ascii=False),
                json.dumps(c.by_language, ensure_ascii=False),
                json.dumps(c.blindspot_for, ensure_ascii=False),
                c.computed_at.isoformat(),
            ]
            for c in rows
        ],
    )


@router.get("/segnali.csv")
async def segnali_csv(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    rows = (
        await session.execute(
            select(BiasSignal, Source.slug)
            .join(Source, BiasSignal.source_id == Source.id)
            .order_by(BiasSignal.id)
        )
    ).all()
    return _csv_response(
        "segnali.csv",
        [
            "source", "signal_type", "axis", "period_start", "period_end",
            "n_articles", "method_version", "computed_at", "value_json",
        ],
        [
            [
                slug, s.signal_type, s.axis or "", s.period_start.isoformat(),
                s.period_end.isoformat(), s.n_articles, s.method_version,
                s.computed_at.isoformat(), json.dumps(s.value, ensure_ascii=False),
            ]
            for s, slug in rows
        ],
    )

"""Healthcheck per Caddy, compose e monitoring; spegnimento locale."""

import asyncio
import logging
import os
import signal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import get_session

log = logging.getLogger(__name__)

router = APIRouter()


def _termina() -> None:
    """Spegnimento morbido del processo (uvicorn gestisce il SIGINT)."""
    os.kill(os.getpid(), signal.SIGINT)


@router.post("/spegni")
async def spegni(request: Request) -> dict[str, str]:
    """Spegne l'app in modalità personale, su richiesta della finestra.

    Chiudere la finestra deve chiudere TUTTO: la finestra chiama questo
    endpoint col token che il launcher ha generato all'avvio (file in
    ~/.opennews, mai esposto). Senza token valido: 404, come se la rotta
    non esistesse — in modalità server l'endpoint è quindi inerte.
    """
    token = os.environ.get("OPENNEWS_SHUTDOWN_TOKEN")
    if (
        not token
        or os.environ.get("OPENNEWS_EMBEDDED_WORKER") != "1"
        or request.headers.get("x-opennews-spegni") != token
    ):
        raise HTTPException(status_code=404, detail="Not Found")
    log.info("spegnimento richiesto dalla finestra: chiudo il giornale")
    asyncio.get_running_loop().call_later(0.3, _termina)
    return {"stato": "spegnimento"}


@router.get("/healthz")
async def healthz(session: Annotated[AsyncSession, Depends(get_session)]) -> dict[str, str]:
    try:
        await session.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:  # l'healthcheck non deve mai propagare errori
        db_status = "error"
    return {"status": "ok", "db": db_status}

"""Healthcheck per Caddy, compose e monitoring."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import get_session

router = APIRouter()


@router.get("/healthz")
async def healthz(session: Annotated[AsyncSession, Depends(get_session)]) -> dict[str, str]:
    try:
        await session.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:  # l'healthcheck non deve mai propagare errori
        db_status = "error"
    return {"status": "ok", "db": db_status}

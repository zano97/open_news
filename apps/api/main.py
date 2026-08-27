"""Punto d'ingresso dell'API e del sito Open News."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from apps.api.routers import annotate, export, health, metodo, pages, settings_panel
from apps.api.templating import STATIC_DIR
from core.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Gli override del pannello admin prevalgono sulle variabili d'ambiente.
    try:
        from core.db import get_sessionmaker
        from core.runtime_settings import load_overrides

        async with get_sessionmaker()() as session:
            await load_overrides(session)
    except Exception:  # DB non pronto (primo avvio): valgono i default
        logging.getLogger("opennews.api").info(
            "override impostazioni non caricati (DB non pronto)"
        )
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        lifespan=lifespan,
        title=settings.app_name,
        description=(
            "Aggregatore di notizie open source: rende visibile chi finanzia "
            "l'informazione, come ogni testata seleziona e racconta le notizie, "
            "e che cosa ciascuna ignora. Licenza AGPL-3.0; dati derivati CC BY-SA 4.0."
        ),
        version="0.1.0",
    )
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(health.router)
    app.include_router(pages.router)
    app.include_router(annotate.router)
    app.include_router(export.router)
    app.include_router(metodo.router)
    app.include_router(settings_panel.router)
    return app


app = create_app()

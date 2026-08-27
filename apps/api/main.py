"""Punto d'ingresso dell'API e del sito Open News."""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from apps.api.routers import annotate, export, health, metodo, pages, settings_panel
from apps.api.templating import STATIC_DIR
from core.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Registro eventi in memoria: visibile dal pannello /impostazioni,
    # così la diagnosi non richiede un terminale.
    from core.logbuffer import install as install_logbuffer

    install_logbuffer()
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
    # Modalità personale (launcher `opennews`, senza Docker): il raccoglitore
    # gira nello stesso processo. Richiede un solo worker uvicorn.
    scheduler = None
    if os.environ.get("OPENNEWS_EMBEDDED_WORKER") == "1":
        from apscheduler.schedulers.asyncio import AsyncIOScheduler

        from apps.worker.jobs import register_jobs

        scheduler = AsyncIOScheduler(timezone="UTC")
        register_jobs(scheduler)
        scheduler.start()
        logging.getLogger("opennews.api").info(
            "raccoglitore incorporato avviato (%d job)", len(scheduler.get_jobs())
        )
    yield
    if scheduler is not None:
        scheduler.shutdown(wait=False)


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

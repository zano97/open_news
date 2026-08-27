"""Punto d'ingresso dell'API e del sito Open News."""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from apps.api.routers import annotate, export, health, metodo, pages
from apps.api.templating import STATIC_DIR
from core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
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
    return app


app = create_app()

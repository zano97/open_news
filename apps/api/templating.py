"""Ambiente Jinja2 condiviso: filtri e variabili globali dell'interfaccia."""

from datetime import UTC, datetime
from pathlib import Path

from fastapi.templating import Jinja2Templates

from core.config import METHOD_VERSION, get_settings

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

_GIORNI = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
_MESI = [
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
]


def data_in_lettere(dt: datetime) -> str:
    """'Giovedì 27 agosto 2026' — data del giorno in lettere, come in testata."""
    local = dt.astimezone(UTC)
    giorno = _GIORNI[local.weekday()].capitalize()
    return f"{giorno} {local.day} {_MESI[local.month - 1]} {local.year}"


def ora_breve(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    return dt.astimezone(UTC).strftime("%H:%M")


def data_breve(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    local = dt.astimezone(UTC)
    return f"{local.day} {_MESI[local.month - 1]} {local.year}"


def build_templates() -> Jinja2Templates:
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    templates.env.filters["data_lettere"] = data_in_lettere
    templates.env.filters["ora_breve"] = ora_breve
    templates.env.filters["data_breve"] = data_breve
    templates.env.globals["app_name"] = get_settings().app_name
    templates.env.globals["method_version"] = METHOD_VERSION
    templates.env.globals["now"] = lambda: datetime.now(UTC)
    return templates


templates = build_templates()

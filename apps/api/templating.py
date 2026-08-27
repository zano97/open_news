"""Ambiente Jinja2 condiviso: filtri (localizzati) e variabili globali."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi.templating import Jinja2Templates
from jinja2 import pass_context
from jinja2.runtime import Context

from core.config import METHOD_VERSION, get_settings
from core.i18n import DEFAULT_LOCALE

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

# Nomi di giorni e mesi per la data in lettere della testata, per lingua.
_GIORNI: dict[str, list[str]] = {
    "it": ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"],
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
    "fr": ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"],
    "de": ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"],
    "es": ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"],
}
_MESI: dict[str, list[str]] = {
    "it": ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
           "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"],
    "en": ["January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December"],
    "fr": ["janvier", "février", "mars", "avril", "mai", "juin",
           "juillet", "août", "septembre", "octobre", "novembre", "décembre"],
    "de": ["Januar", "Februar", "März", "April", "Mai", "Juni",
           "Juli", "August", "September", "Oktober", "November", "Dezember"],
    "es": ["enero", "febrero", "marzo", "abril", "mayo", "junio",
           "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"],
}


def _ctx_locale(context: Context) -> str:
    value = context.get("locale", DEFAULT_LOCALE)
    return value if value in _GIORNI else DEFAULT_LOCALE


def data_in_lettere(dt: datetime, locale: str = DEFAULT_LOCALE) -> str:
    """La data del giorno in lettere, come in testata ('Giovedì 27 agosto 2026')."""
    local = dt.astimezone(UTC)
    giorno = _GIORNI[locale][local.weekday()]
    mese = _MESI[locale][local.month - 1]
    if locale == "en":
        return f"{giorno}, {mese} {local.day}, {local.year}"
    if locale == "de":
        return f"{giorno}, {local.day}. {mese} {local.year}"
    return f"{giorno.capitalize()} {local.day} {mese} {local.year}"


@pass_context
def _filtro_data_lettere(context: Context, dt: datetime) -> str:
    return data_in_lettere(dt, _ctx_locale(context))


def ora_breve(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    return dt.astimezone(UTC).strftime("%H:%M")


@pass_context
def _filtro_data_breve(context: Context, dt: datetime | None) -> str:
    if dt is None:
        return "—"
    locale = _ctx_locale(context)
    local = dt.astimezone(UTC)
    mese = _MESI[locale][local.month - 1]
    if locale == "en":
        return f"{mese} {local.day}, {local.year}"
    if locale == "de":
        return f"{local.day}. {mese} {local.year}"
    return f"{local.day} {mese} {local.year}"


def build_templates() -> Jinja2Templates:
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    templates.env.filters["data_lettere"] = _filtro_data_lettere
    templates.env.filters["ora_breve"] = ora_breve
    templates.env.filters["data_breve"] = _filtro_data_breve
    templates.env.globals["app_name"] = get_settings().app_name
    templates.env.globals["method_version"] = METHOD_VERSION
    templates.env.globals["now"] = lambda: datetime.now(UTC)

    # Titolo della story nella lingua dell'interfaccia (traduzione marcata).
    from core.nlp.translate import headline_for

    # Titolo per la lingua dell'interfaccia: originale in lingua quando
    # esiste, poi traduzione automatica, poi il titolo neutro com'è.
    templates.env.globals["titolo_story"] = (
        lambda story, locale: headline_for(story, locale)[0]
    )
    templates.env.globals["titolo_tradotto"] = (
        lambda story, locale: headline_for(story, locale)[1]
    )
    return templates


templates = build_templates()


def render_context(**extra: Any) -> dict[str, Any]:
    return dict(extra)

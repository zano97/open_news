"""Internazionalizzazione dell'interfaccia: cataloghi YAML per lingua.

Le stringhe dell'interfaccia vivono in ``apps/web/translations/{locale}.yaml``
(chiavi piatte con punti, segnaposto ``{nome}`` in stile ``str.format``).
L'italiano è il catalogo di riferimento; le altre lingue devono avere le
stesse chiavi (un test lo garantisce). Fallback: lingua richiesta → inglese
→ italiano → la chiave stessa (mai una pagina rotta per una traduzione
mancante).

La lingua si sceglie esplicitamente dal selettore in testata (cookie);
niente auto-rilevamento dall'Accept-Language: comportamento deterministico,
documentato in ADR-0016.
"""

import time
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

import yaml

TRANSLATIONS_DIR = Path(__file__).resolve().parent.parent / "apps" / "web" / "translations"

SUPPORTED_LOCALES: tuple[str, ...] = ("it", "en", "fr", "de", "es")
DEFAULT_LOCALE = "it"
LOCALE_COOKIE = "opennews_lingua"

LOCALE_NAMES = {
    "it": "Italiano",
    "en": "English",
    "fr": "Français",
    "de": "Deutsch",
    "es": "Español",
}


@lru_cache(maxsize=8)
def catalog(locale: str) -> dict[str, str]:
    path = TRANSLATIONS_DIR / f"{locale}.yaml"
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(k): str(v) for k, v in raw.items()}


def translate(locale: str, key: str, **kwargs: object) -> str:
    """Traduzione con fallback a catena; i segnaposto mancanti non esplodono."""
    for candidate in (locale, "en", DEFAULT_LOCALE):
        value = catalog(candidate).get(key)
        if value is not None:
            break
    else:  # pragma: no cover - irraggiungibile: il ciclo copre sempre DEFAULT
        value = None
    if value is None:
        return key
    if kwargs:
        try:
            return value.format(**kwargs)
        except (KeyError, IndexError):
            return value
    return value


def make_translator(locale: str) -> Callable[..., str]:
    def t(key: str, **kwargs: object) -> str:
        return translate(locale, key, **kwargs)

    return t


def normalize_locale(value: str | None) -> str | None:
    if not value:
        return None
    code = value.strip().lower()[:2]
    return code if code in SUPPORTED_LOCALES else None


def resolve_locale(query_value: str | None, cookie_value: str | None) -> str:
    """Priorità: parametro esplicito > cookie > default. Deterministico."""
    return (
        normalize_locale(query_value)
        or normalize_locale(cookie_value)
        or DEFAULT_LOCALE
    )


def reset_cache() -> None:
    """Per i test e per ricaricare i cataloghi modificati."""
    catalog.cache_clear()


# Lingue davvero usate dal lettore (ultimo uso, epoch). Serve al job di
# traduzione dei titoli: prima le lingue che qualcuno sta guardando, il
# resto quando avanza tempo. Solo in memoria: al riavvio si riparte dal
# default, e il primo caricamento di pagina ripopola.
_LOCALE_USES: dict[str, float] = {}


def note_locale_use(locale: str) -> None:
    if locale in SUPPORTED_LOCALES:
        _LOCALE_USES[locale] = time.time()


def locales_by_priority(days: int = 7) -> tuple[str, ...]:
    """Le lingue dell'interfaccia usate negli ultimi `days` giorni per prime
    (dalla più recente), poi le altre nell'ordine di ``SUPPORTED_LOCALES``."""
    cutoff = time.time() - days * 86400
    usate = sorted(
        (code for code, quando in _LOCALE_USES.items() if quando >= cutoff),
        key=lambda code: -_LOCALE_USES[code],
    )
    return tuple(usate + [c for c in SUPPORTED_LOCALES if c not in usate])

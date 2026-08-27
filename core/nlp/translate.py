"""Traduzione automatica dei titoli NEUTRI delle story (Argos Translate).

Regole:
- si traducono SOLO i titoli neutri scelti dal sistema, mai i titoli delle
  testate: la loro formulazione è il dato che misuriamo (framing) e
  tradurla significherebbe alterarlo;
- il motore è Argos Translate (open source, offline, extra ``[translate]``):
  nessun servizio a pagamento, nessun dato che lascia la macchina;
- ogni traduzione è marcata come automatica nell'interfaccia e registrata
  nella provenance con metodo e coppia di lingue;
- senza l'extra installato non succede nulla: si mostra l'originale.
"""

import logging
from collections.abc import Iterable
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from core.i18n import SUPPORTED_LOCALES
from core.models import Story
from core.provenance import record

log = logging.getLogger(__name__)

METHOD_NAME = "argos-translate-v1"


class Translator(Protocol):
    name: str

    def available_pairs(self) -> set[tuple[str, str]]: ...

    def translate(self, text: str, source: str, target: str) -> str | None: ...


class ArgosTranslator:  # pragma: no cover - richiede l'extra [translate] e i modelli
    """Backend Argos Translate: coppie di lingue installate localmente."""

    name = METHOD_NAME

    def __init__(self) -> None:
        import argostranslate.translate  # type: ignore[import-not-found]

        self._module = argostranslate.translate
        self._pairs: set[tuple[str, str]] = set()
        for lang in self._module.get_installed_languages():
            for other in lang.translations_to:
                self._pairs.add((lang.code, other.to_lang.code))

    def available_pairs(self) -> set[tuple[str, str]]:
        return self._pairs

    def translate(self, text: str, source: str, target: str) -> str | None:
        if (source, target) not in self._pairs:
            return None
        result = str(self._module.translate(text, source, target)).strip()
        return result or None


_translator: Translator | None = None
_translator_checked = False


def get_translator() -> Translator | None:
    """Il traduttore locale, se l'extra [translate] è installato; altrimenti None."""
    global _translator, _translator_checked
    if not _translator_checked:
        _translator_checked = True
        try:
            _translator = ArgosTranslator()
        except ImportError:
            log.info(
                "argostranslate non installato: i titoli restano in lingua "
                "originale (extra [translate] + scripts/fetch_translation_models.py)"
            )
            _translator = None
    return _translator


def set_translator(translator: Translator | None) -> None:
    """Per i test (e per backend alternativi)."""
    global _translator, _translator_checked
    _translator = translator
    _translator_checked = True


def story_language(story: Story) -> str | None:
    """Lingua del titolo neutro = lingua dominante degli articoli del cluster."""
    languages = [a.language for a in story.articles if a.language]
    if not languages:
        return None
    return max(set(languages), key=languages.count)


async def translate_story_title(
    session: AsyncSession,
    story: Story,
    *,
    targets: Iterable[str] = SUPPORTED_LOCALES,
    translator: Translator | None = None,
) -> int:
    """Completa le traduzioni mancanti del titolo neutro. Ritorna quante nuove."""
    translator = translator or get_translator()
    if translator is None:
        return 0
    source = story_language(story)
    if source is None:
        return 0
    translations = dict(story.title_translations or {})
    added = 0
    for target in targets:
        if target == source or target in translations:
            continue
        translated = translator.translate(story.title_neutral, source, target)
        if not translated or translated.strip() == story.title_neutral.strip():
            continue
        translations[target] = translated
        added += 1
    if added:
        story.title_translations = translations
        await record(
            session,
            entity_type="story",
            entity_id=story.id,
            field="title_translations",
            method=translator.name,
            inputs={"source": source, "targets": sorted(translations)},
        )
        await session.flush()
    return added


def display_title(story: Story, locale: str) -> tuple[str, bool]:
    """(titolo da mostrare, è_una_traduzione) per la lingua dell'interfaccia."""
    translations = story.title_translations or {}
    translated = translations.get(locale)
    if translated:
        return translated, True
    return story.title_neutral, False


def headline_for(story: Story, locale: str) -> tuple[str, bool]:
    """Titolo della story nella lingua del lettore, quando esiste.

    Il titolo neutro è già la formulazione di una testata (l'articolo più
    vicino al centroide): se non è nella lingua dell'interfaccia ma la story
    ha versioni in quella lingua, si mostra la prima pubblicata tra queste —
    stesso criterio, vincolato alla lingua, e un originale batte sempre una
    traduzione automatica. Ordine: neutro se già in lingua → originale in
    lingua → traduzione automatica → neutro com'è.
    Richiede story.articles già caricati (le pagine che la usano li hanno).
    """
    articles = list(story.articles or [])
    neutral_language = next(
        (a.language for a in articles if a.title == story.title_neutral), None
    )
    if neutral_language == locale:
        return story.title_neutral, False
    in_lingua = [a for a in articles if a.language == locale and a.title]
    if in_lingua:
        primo = min(in_lingua, key=lambda a: a.published_at or a.fetched_at)
        return primo.title, False
    return display_title(story, locale)

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
import re
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

    def _install_pair(self, source: str, target: str) -> bool:
        """Scarica e installa un modello di coppia dall'indice Argos.

        I modelli arrivano da argosopentech.com (gratuito, in allowlist);
        ogni coppia si scarica UNA volta (~100 MB) e poi lavora offline.
        """
        try:
            import argostranslate.package  # type: ignore[import-not-found]

            argostranslate.package.update_package_index()
            for pkg in argostranslate.package.get_available_packages():
                if pkg.from_code == source and pkg.to_code == target:
                    log.info("scarico il modello di traduzione %s→%s", source, target)
                    argostranslate.package.install_from_path(pkg.download())
                    self._pairs.add((source, target))
                    return True
        except Exception as exc:  # rete assente o indice irraggiungibile
            log.info("modello %s→%s non installabile ora: %s", source, target, exc)
        return False

    def ensure_pair(self, source: str, target: str) -> bool:
        """Garantisce la coppia, direttamente o con perno sull'inglese."""
        if (source, target) in self._pairs:
            return True
        if self._install_pair(source, target):
            return True
        # Perno: source→en + en→target (Argos concatena da solo).
        ok_a = (source, "en") in self._pairs or self._install_pair(source, "en")
        ok_b = ("en", target) in self._pairs or self._install_pair("en", target)
        if ok_a and ok_b:
            self._pairs.add((source, target))
            return True
        return False

    def translate(self, text: str, source: str, target: str) -> str | None:
        if (source, target) not in self._pairs and not self.ensure_pair(source, target):
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
    """Completa le traduzioni mancanti del titolo neutro. Ritorna quante nuove.

    Il motore è SOLO Argos (offline; scarica da sé le coppie che servono):
    il generatore LLM resta riservato ai riassunti, per scelta esplicita.
    """
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
        # Argos è CPU (e al primo giro scarica i modelli): su un thread,
        # o bloccherebbe l'intera app per minuti.
        import asyncio

        translated = await asyncio.to_thread(
            translator.translate, story.title_neutral, source, target
        )
        if not translated or translated.strip() == story.title_neutral.strip():
            continue
        translations[target] = translated
        added += 1
    if added:
        story.title_translations = translations
        metodo = translator.name
        await record(
            session,
            entity_type="story",
            entity_id=story.id,
            field="title_translations",
            method=metodo,
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


_PAROLA_RE = re.compile(r"\w+", re.UNICODE)
_ANNO_RE = re.compile(r"^(19|20)\d\d$")


def _parole_forti(testo: str) -> set[str]:
    """Nomi propri e numeri di un titolo: sopravvivono alla traduzione.

    Sono l'aggancio con cui verificare che due titoli in lingue diverse
    parlino della stessa notizia. Gli anni (2026…) sono esclusi: compaiono
    in titoli di notizie qualsiasi e aggancerebbero tutto con tutto.
    """
    return {
        t.lower()
        for t in _PAROLA_RE.findall(testo)
        if (t[:1].isupper() and len(t) >= 4)
        or (t.isdigit() and len(t) >= 2 and not _ANNO_RE.match(t))
    }


def _stessa_notizia(a: set[str], b: set[str]) -> bool:
    """Vero se due insiemi di parole forti condividono un aggancio.

    Basta un prefisso comune di 4 caratteri: cattura anche i cognati tra
    lingue vicine ("Governo"/"Government", "pensioni"/"pension")."""
    return any(x[:4] == y[:4] for x in a for y in b)


def headline_subtitle(story: Story, locale: str) -> tuple[str, bool] | None:
    """Riga tra parentesi SOTTO il titolo: il senso nella lingua del lettore.

    Il titolo resta sempre quello originale (è il dato); quando non è nella
    lingua dell'interfaccia, sotto compare tra parentesi: la traduzione
    automatica se esiste (marcata), altrimenti il titolo di una versione
    nella lingua del lettore (la prima pubblicata: è la formulazione di una
    testata, elencata comunque tra le versioni). La versione in lingua deve
    però condividere col titolo neutro almeno un nome proprio o un numero:
    un cluster può contenere un articolo fuori posto, e meglio nessun
    sottotitolo che il titolo di un'ALTRA notizia. Nessuna delle due → None.
    Ritorna (testo, è_traduzione_automatica).
    Richiede story.articles già caricati (le pagine che la usano li hanno).
    """
    articles = list(story.articles or [])
    neutral_language = next(
        (a.language for a in articles if a.title == story.title_neutral), None
    ) or story_language(story)
    if neutral_language == locale:
        return None
    translations = story.title_translations or {}
    if translations.get(locale):
        return translations[locale], True
    # Versione nella lingua del lettore: SOLO quando la lingua rilevata e
    # quella della testata concordano. Il rilevatore sui titoli brevi può
    # sbagliare (un titolo norvegese classificato "it"): la doppia
    # conferma evita sottotitoli nella lingua sbagliata.
    in_lingua = [
        a
        for a in articles
        if a.language == locale
        and a.source is not None
        and a.source.language == locale
        and a.title
        and a.title != story.title_neutral
    ]
    # Aggancio alla notizia: senza un nome proprio o numero in comune col
    # titolo neutro, la "versione in lingua" potrebbe essere un articolo
    # finito nel cluster per errore. (Se uno dei due titoli non ha parole
    # forti non si può giudicare: si lascia passare.)
    forti_titolo = _parole_forti(story.title_neutral)
    if forti_titolo:
        in_lingua = [
            a
            for a in in_lingua
            if not (forti := _parole_forti(a.title))
            or _stessa_notizia(forti, forti_titolo)
        ]
    if in_lingua:
        # Meglio un titolo arrivato dal feed (con snippet): quelli via GDELT
        # hanno apostrofi persi e punteggiatura ricomposta alla meno peggio.
        puliti = [a for a in in_lingua if (a.snippet or "").strip()] or in_lingua
        primo = min(puliti, key=lambda a: a.published_at or a.fetched_at)
        return primo.title, False
    return None

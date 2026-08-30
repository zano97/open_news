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
import time
from collections import deque
from collections.abc import Iterable
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from core.i18n import SUPPORTED_LOCALES
from core.models import Story
from core.provenance import record

log = logging.getLogger(__name__)

METHOD_NAME = "argos-translate-v1"

# L'indice dei modelli Argos si riscarica al più una volta l'ora; una coppia
# senza modello va in pausa per ore invece di riscaricare l'indice a ogni
# giro: erano QUESTI tentativi a mangiarsi il tempo del job di traduzione.
INDEX_TTL_SECONDS = 3600.0
PAIR_RETRY_COOLDOWN_SECONDS = 6 * 3600.0

# Esiti recenti delle traduzioni, per la Diagnostica: se un titolo resta
# non tradotto, qui si legge il PERCHÉ (coppia mancante, testo identico…).
LAST_ESITI: deque[dict[str, object]] = deque(maxlen=60)

# Epoch dell'ultima traduzione SALVATA: il client la usa per accorgersi
# che i sottotitoli appena tradotti in background sono pronti da mostrare.
LAST_TRANSLATION_AT: float | None = None


def _registra_esito(story_id: int | None, source: str, target: str, esito: str) -> None:
    LAST_ESITI.appendleft(
        {
            "quando": time.time(),
            "story_id": story_id,
            "coppia": f"{source}→{target}",
            "esito": esito,
        }
    )


def riepilogo_esiti() -> dict[str, object]:
    """Sintesi per il pannello Diagnostica: conteggi per esito e coppie ferme."""
    conteggi: dict[str, int] = {}
    coppie_ferme: dict[str, str] = {}
    for riga in LAST_ESITI:
        esito = str(riga["esito"])
        conteggi[esito] = conteggi.get(esito, 0) + 1
        if esito != "ok":
            coppie_ferme.setdefault(str(riga["coppia"]), esito)
    return {"conteggi": conteggi, "coppie_ferme": coppie_ferme}


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
        # Anti-spreco: l'indice si riscarica al più ogni INDEX_TTL_SECONDS,
        # una coppia fallita non si ritenta prima del cooldown. Prima di
        # queste due guardie, OGNI titolo con coppia mancante riscaricava
        # l'indice via rete a ogni giro, e il job non finiva mai il lavoro.
        self._indice_al: float | None = None
        self._coppie_negate: dict[tuple[str, str], float] = {}

    def available_pairs(self) -> set[tuple[str, str]]:
        return self._pairs

    def _install_pair(self, source: str, target: str) -> bool:
        """Scarica e installa un modello di coppia dall'indice Argos.

        I modelli arrivano da argosopentech.com (gratuito, in allowlist);
        ogni coppia si scarica UNA volta (~100 MB) e poi lavora offline.
        """
        try:
            import argostranslate.package  # type: ignore[import-not-found]

            if (
                self._indice_al is None
                or time.monotonic() - self._indice_al >= INDEX_TTL_SECONDS
            ):
                # Si segna il TENTATIVO (non il successo): anche un indice
                # irraggiungibile non va rimartellato per un'ora.
                self._indice_al = time.monotonic()
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
        negata = self._coppie_negate.get((source, target))
        if negata is not None:
            if time.monotonic() - negata < PAIR_RETRY_COOLDOWN_SECONDS:
                return False
            del self._coppie_negate[(source, target)]
        if self._install_pair(source, target):
            return True
        # Perno: source→en + en→target (Argos concatena da solo).
        ok_a = (source, "en") in self._pairs or self._install_pair(source, "en")
        ok_b = ("en", target) in self._pairs or self._install_pair("en", target)
        if ok_a and ok_b:
            self._pairs.add((source, target))
            return True
        self._coppie_negate[(source, target)] = time.monotonic()
        return False

    def translate(self, text: str, source: str, target: str) -> str | None:
        if (source, target) not in self._pairs and not self.ensure_pair(source, target):
            return None
        try:
            result = str(self._module.translate(text, source, target)).strip()
        except Exception as exc:  # un testo indigesto non deve fermare il giro
            log.warning("traduzione %s→%s fallita: %s", source, target, exc)
            return None
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
    """Lingua dominante degli articoli del cluster."""
    languages = [a.language for a in story.articles if a.language]
    if not languages:
        return None
    return max(set(languages), key=languages.count)


def neutral_title_language(story: Story) -> str | None:
    """Lingua del TITOLO NEUTRO: quella dell'articolo che l'ha fornito.

    Non è detto che coincida con la lingua dominante del cluster (un titolo
    inglese può guidare una story per lo più italiana): tradurre con la
    lingua sorgente sbagliata produce testi identici o senza senso, che
    venivano scartati — ed era uno dei motivi dei titoli mai tradotti.
    """
    return next(
        (
            a.language
            for a in (story.articles or [])
            if a.language and a.title == story.title_neutral
        ),
        None,
    ) or story_language(story)


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
    Una traduzione che torna IDENTICA all'originale (nomi propri, coppia
    che non morde) si registra come stringa vuota: la UI mostra l'originale
    e il giro successivo non riprova all'infinito lo stesso testo.
    """
    translator = translator or get_translator()
    if translator is None:
        return 0
    source = neutral_title_language(story)
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
        if not translated:
            _registra_esito(story.id, source, target, "coppia non disponibile")
            continue
        if translated.strip() == story.title_neutral.strip():
            translations[target] = ""  # sentinella: tentata, uscita identica
            added += 1
            _registra_esito(story.id, source, target, "identica all'originale")
            continue
        translations[target] = translated
        added += 1
        _registra_esito(story.id, source, target, "ok")
    if added:
        global LAST_TRANSLATION_AT
        LAST_TRANSLATION_AT = time.time()
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


async def stories_to_translate(
    session: AsyncSession, *, limit: int = 200
) -> list[Story]:
    """Le story da tradurre, NELL'ORDINE in cui il lettore le vedrà.

    Stessa finestra e stesso peso della prima pagina (core.ranking): prima
    il job traduceva «le più recenti», la pagina mostrava «le più pesate»,
    e le due liste divergevano — risultato: prima pagina piena di titoli
    mai tradotti mentre il job lavorava su story che nessuno guardava.
    Finestra vuota (archivio fermo): si ripiega sulle più recenti.
    """
    from sqlalchemy import select as sql_select

    from core.ranking import copertura_recente, finestra_attualita, peso_attualita

    candidate = list(
        (
            await session.execute(
                sql_select(Story)
                .where(Story.last_seen >= finestra_attualita())
                .order_by(Story.last_seen.desc())
                .limit(max(limit * 2, 400))
            )
        ).scalars()
    )
    if not candidate:
        candidate = list(
            (
                await session.execute(
                    sql_select(Story).order_by(Story.last_seen.desc()).limit(limit)
                )
            ).scalars()
        )
    recenti = await copertura_recente(session, [s.id for s in candidate])
    candidate.sort(
        key=lambda s: -peso_attualita(recenti.get(s.id, 1), s.last_seen)
    )
    return candidate[:limit]


async def translate_missing(
    session: AsyncSession,
    story_ids: list[int],
    locale: str,
    *,
    translator: Translator | None = None,
) -> int:
    """Traduzioni mirate: solo le story elencate, solo nella lingua data."""
    from sqlalchemy import select as sql_select

    fatte = 0
    for story_id in story_ids:
        story = (
            await session.execute(sql_select(Story).where(Story.id == story_id))
        ).scalar_one_or_none()
        if story is None:
            continue
        try:
            nuove = await translate_story_title(
                session, story, targets=(locale,), translator=translator
            )
            if nuove:
                await session.commit()  # al sicuro subito, transazioni corte
            fatte += nuove
        except Exception as exc:  # una story indigesta non ferma le altre
            await session.rollback()
            log.warning("titolo della story %s non tradotto: %s", story_id, exc)
    return fatte


# Story già in lavorazione on-demand: mai due volte lo stesso lavoro insieme.
_KICK_IN_CORSO: set[tuple[int, str]] = set()


def kick_translations(story_ids: list[int], locale: str) -> object | None:
    """Fuoco-e-dimentica dalla prima pagina: le story VISIBILI senza
    traduzione nella lingua del lettore si traducono subito in background,
    senza aspettare il giro dei 15 minuti. Al prossimo caricamento la riga
    tra parentesi c'è. Ritorna il task (o None se non c'è nulla da fare)."""
    import asyncio

    if get_translator() is None:
        return None
    nuovi = [s for s in story_ids if (s, locale) not in _KICK_IN_CORSO][:12]
    if not nuovi:
        return None
    for story_id in nuovi:
        _KICK_IN_CORSO.add((story_id, locale))

    async def _run() -> None:
        try:
            from core.db import get_sessionmaker

            maker = get_sessionmaker()
            async with maker() as session:
                fatte = await translate_missing(session, nuovi, locale)
                await session.commit()
            if fatte:
                log.info(
                    "tradotti on-demand %d titoli in %s (prima pagina)",
                    fatte, locale,
                )
        except Exception as exc:  # DB occupato o Argos in download: riproverà
            log.info("traduzioni on-demand rimandate: %s", exc)
        finally:
            for story_id in nuovi:
                _KICK_IN_CORSO.discard((story_id, locale))

    return asyncio.create_task(_run())


def article_translation(article: object, locale: str) -> str | None:
    """La traduzione VISIBILE del titolo di una versione, se in cache.

    Aiuto di lettura, mai il dato: il titolo originale resta protagonista
    in pagina. La sentinella vuota ("" = uscita identica) resta nascosta.
    """
    lingua = getattr(article, "language", None)
    fonte = getattr(article, "source", None)
    if lingua == locale or (fonte is not None and fonte.language == locale):
        return None
    cache = getattr(article, "title_translations", None) or {}
    testo = cache.get(locale)
    return testo or None


def _lingua_versione(article: object) -> str | None:
    """Sorgente per tradurre una versione: solo con la DOPPIA conferma
    (lingua rilevata == lingua dichiarata della testata), come per i
    sottotitoli: il rilevatore sui titoli brevi sbaglia, la testata no."""
    lingua = getattr(article, "language", None)
    fonte = getattr(article, "source", None)
    if lingua and fonte is not None and fonte.language == lingua:
        return str(lingua)
    return None


async def translate_articles(
    session: AsyncSession,
    article_ids: list[int],
    locale: str,
    *,
    translator: Translator | None = None,
) -> int:
    """Traduce i titoli delle VERSIONI elencate, nella sola lingua data.

    Cache per articolo con sentinella (mai lo stesso testo all'infinito),
    commit per articolo (transazioni corte), LAST_TRANSLATION_AT avanzato
    così la pastiglia «nuove notizie» avvisa quando sono pronte.
    """
    import asyncio

    from sqlalchemy import select as sql_select

    from core.models import Article

    translator = translator or get_translator()
    if translator is None:
        return 0
    fatte = 0
    for article_id in article_ids:
        article = (
            await session.execute(
                sql_select(Article).where(Article.id == article_id)
            )
        ).scalar_one_or_none()
        if article is None:
            continue
        source = _lingua_versione(article)
        if source is None or source == locale:
            continue
        cache = dict(article.title_translations or {})
        if locale in cache:
            continue
        try:
            translated = await asyncio.to_thread(
                translator.translate, article.title, source, locale
            )
        except Exception as exc:  # un titolo indigesto non ferma gli altri
            log.warning("versione %s non tradotta: %s", article_id, exc)
            continue
        if not translated:
            _registra_esito(None, source, locale, "coppia non disponibile")
            continue
        if translated.strip() == article.title.strip():
            cache[locale] = ""  # sentinella: tentata, uscita identica
        else:
            cache[locale] = translated
            fatte += 1
        article.title_translations = cache
        global LAST_TRANSLATION_AT
        LAST_TRANSLATION_AT = time.time()
        await session.commit()  # al sicuro subito, transazioni corte
    return fatte


# Versioni già in lavorazione on-demand: mai due volte lo stesso lavoro.
_KICK_VERSIONI: set[tuple[int, str]] = set()


def kick_article_translations(
    article_ids: list[int], locale: str
) -> object | None:
    """Fuoco-e-dimentica dalle pagine: le versioni VISIBILI senza
    traduzione si traducono subito in background (limite per giro)."""
    import asyncio

    if get_translator() is None:
        return None
    nuovi = [a for a in article_ids if (a, locale) not in _KICK_VERSIONI][:20]
    if not nuovi:
        return None
    for article_id in nuovi:
        _KICK_VERSIONI.add((article_id, locale))

    async def _run() -> None:
        try:
            from core.db import get_sessionmaker

            maker = get_sessionmaker()
            async with maker() as session:
                fatte = await translate_articles(session, nuovi, locale)
            if fatte:
                log.info(
                    "tradotte on-demand %d versioni in %s", fatte, locale
                )
        except Exception as exc:  # DB occupato o Argos in download: riproverà
            log.info("traduzioni delle versioni rimandate: %s", exc)
        finally:
            for article_id in nuovi:
                _KICK_VERSIONI.discard((article_id, locale))

    return asyncio.create_task(_run())


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
    neutral_language = neutral_title_language(story)
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

"""Rilevamento lingua leggero e deterministico, senza modelli da scaricare.

Strategia a due passi: prima la scrittura (cirillico, arabo, ebraico, kana,
han, devanagari), poi — per l'alfabeto latino — il conteggio di parole
funzionali ad alta frequenza. Copre le lingue delle fonti del catalogo.
Se l'extra `[ml]` con lingua-py è installato, viene preferito quello.
Il metodo usato è sempre dichiarato nel valore di ritorno.
"""

import re
import unicodedata
from dataclasses import dataclass

_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)

_STOPWORDS: dict[str, frozenset[str]] = {
    "it": frozenset(
        [
            "il",
            "lo",
            "la",
            "i",
            "gli",
            "le",
            "un",
            "una",
            "uno",
            "di",
            "a",
            "da",
            "in",
            "con",
            "su",
            "per",
            "tra",
            "fra",
            "che",
            "chi",
            "cui",
            "non",
            "come",
            "dove",
            "quando",
            "perché",
            "più",
            "anche",
            "ancora",
            "ma",
            "se",
            "è",
            "sono",
            "era",
            "stato",
            "hanno",
            "ha",
            "del",
            "della",
            "dei",
            "delle",
            "nel",
            "nella",
            "alla",
            "agli",
            "questo",
            "questa",
            "questi",
            "queste",
            "sul",
            "sulla",
            "essere",
            "fare",
            "dopo",
            "prima",
            "contro",
            "ogni",
            "tutto",
            "tutti",
            "anni",
            "anno",
            "oggi",
            "due",
            "tre",
        ]
    ),
    "en": frozenset(
        [
            "the",
            "a",
            "an",
            "of",
            "to",
            "in",
            "on",
            "for",
            "with",
            "at",
            "by",
            "from",
            "and",
            "or",
            "but",
            "not",
            "is",
            "are",
            "was",
            "were",
            "be",
            "been",
            "has",
            "have",
            "had",
            "he",
            "she",
            "it",
            "they",
            "we",
            "you",
            "this",
            "that",
            "these",
            "those",
            "as",
            "if",
            "when",
            "where",
            "who",
            "what",
            "which",
            "will",
            "would",
            "could",
            "should",
            "there",
            "their",
            "his",
            "her",
            "its",
            "about",
            "after",
            "before",
            "more",
            "most",
            "other",
            "some",
            "such",
            "only",
            "new",
            "says",
            "said",
        ]
    ),
    "fr": frozenset(
        [
            "le",
            "la",
            "les",
            "un",
            "une",
            "des",
            "du",
            "de",
            "à",
            "au",
            "aux",
            "et",
            "ou",
            "mais",
            "dans",
            "sur",
            "pour",
            "par",
            "avec",
            "sans",
            "ne",
            "pas",
            "plus",
            "est",
            "sont",
            "était",
            "été",
            "être",
            "avoir",
            "il",
            "elle",
            "ils",
            "elles",
            "nous",
            "vous",
            "qui",
            "que",
            "quoi",
            "dont",
            "où",
            "quand",
            "comme",
            "si",
            "ce",
            "cette",
            "ces",
            "son",
            "sa",
            "ses",
            "leur",
            "leurs",
            "après",
            "avant",
            "contre",
            "tout",
            "tous",
            "toute",
            "selon",
            "aussi",
            "encore",
            "ans",
        ]
    ),
    "de": frozenset(
        [
            "der",
            "die",
            "das",
            "den",
            "dem",
            "des",
            "ein",
            "eine",
            "einen",
            "einem",
            "einer",
            "und",
            "oder",
            "aber",
            "nicht",
            "ist",
            "sind",
            "war",
            "waren",
            "sein",
            "hat",
            "haben",
            "hatte",
            "im",
            "in",
            "auf",
            "für",
            "mit",
            "von",
            "zu",
            "aus",
            "bei",
            "nach",
            "über",
            "unter",
            "gegen",
            "durch",
            "er",
            "sie",
            "es",
            "wir",
            "ihr",
            "wenn",
            "als",
            "auch",
            "noch",
            "nur",
            "schon",
            "sich",
            "wird",
            "werden",
            "wurde",
            "kann",
            "können",
            "soll",
            "mehr",
            "sehr",
            "jahr",
            "jahre",
            "heute",
        ]
    ),
    "es": frozenset(
        [
            "el",
            "la",
            "los",
            "las",
            "un",
            "una",
            "unos",
            "unas",
            "de",
            "del",
            "a",
            "al",
            "en",
            "con",
            "por",
            "para",
            "sin",
            "sobre",
            "entre",
            "y",
            "o",
            "pero",
            "no",
            "es",
            "son",
            "era",
            "fue",
            "ser",
            "estar",
            "tiene",
            "han",
            "que",
            "quien",
            "cual",
            "donde",
            "cuando",
            "como",
            "si",
            "este",
            "esta",
            "estos",
            "estas",
            "ese",
            "esa",
            "su",
            "sus",
            "más",
            "también",
            "todavía",
            "después",
            "antes",
            "contra",
            "todo",
            "todos",
            "años",
            "año",
            "hoy",
            "dos",
            "tres",
            "según",
        ]
    ),
    "pt": frozenset(
        [
            "o",
            "a",
            "os",
            "as",
            "um",
            "uma",
            "uns",
            "umas",
            "de",
            "do",
            "da",
            "dos",
            "das",
            "em",
            "no",
            "na",
            "nos",
            "nas",
            "com",
            "por",
            "para",
            "sem",
            "sobre",
            "entre",
            "e",
            "ou",
            "mas",
            "não",
            "é",
            "são",
            "era",
            "foi",
            "ser",
            "estar",
            "tem",
            "têm",
            "que",
            "quem",
            "qual",
            "onde",
            "quando",
            "como",
            "se",
            "este",
            "esta",
            "esse",
            "essa",
            "seu",
            "sua",
            "seus",
            "suas",
            "mais",
            "também",
            "depois",
            "antes",
            "contra",
            "todo",
            "todos",
            "anos",
            "ano",
            "hoje",
            "já",
            "não",
        ]
    ),
    "nl": frozenset(
        [
            "de",
            "het",
            "een",
            "van",
            "in",
            "op",
            "voor",
            "met",
            "aan",
            "bij",
            "uit",
            "over",
            "onder",
            "tegen",
            "door",
            "en",
            "of",
            "maar",
            "niet",
            "is",
            "zijn",
            "was",
            "waren",
            "heeft",
            "hebben",
            "had",
            "hij",
            "zij",
            "ze",
            "wij",
            "jullie",
            "die",
            "dat",
            "deze",
            "dit",
            "als",
            "toen",
            "waar",
            "wie",
            "wat",
            "welke",
            "zal",
            "zou",
            "kan",
            "kunnen",
            "moet",
            "meer",
            "zeer",
            "jaar",
            "jaren",
            "vandaag",
            "ook",
            "nog",
            "al",
            "naar",
        ]
    ),
}

ALL_STOPWORDS: frozenset[str] = frozenset().union(*_STOPWORDS.values())
"""Unione delle stopword di tutte le lingue coperte (usata dall'embedder hashing)."""

_MIN_SCORE = 0.10
_MIN_MARGIN = 0.02


@dataclass(frozen=True)
class LanguageGuess:
    language: str | None
    confidence: float
    method: str


def _script_of(text: str) -> str | None:
    counts: dict[str, int] = {}
    for char in text:
        if not char.isalpha():
            continue
        try:
            name = unicodedata.name(char)
        except ValueError:
            continue
        for script in (
            "CYRILLIC",
            "ARABIC",
            "HEBREW",
            "HIRAGANA",
            "KATAKANA",
            "CJK",
            "DEVANAGARI",
            "HANGUL",
            "GREEK",
            "LATIN",
        ):
            if name.startswith(script):
                counts[script] = counts.get(script, 0) + 1
                break
    if not counts:
        return None
    return max(counts, key=lambda k: counts[k])


def _detect_cyrillic(text: str) -> LanguageGuess:
    ukrainian_markers = set("іїєґ")
    russian_markers = set("ыъэё")
    chars = set(text.lower())
    if chars & ukrainian_markers:
        return LanguageGuess("uk", 0.9, "script+markers")
    if chars & russian_markers:
        return LanguageGuess("ru", 0.9, "script+markers")
    return LanguageGuess("ru", 0.5, "script")


def detect_language(text: str) -> LanguageGuess:
    """Ritorna (lingua ISO 639-1 | None, confidenza 0..1, metodo)."""
    text = text.strip()
    if not text:
        return LanguageGuess(None, 0.0, "empty")

    try:  # backend opzionale di qualità superiore (extra [ml])
        from lingua import LanguageDetectorBuilder  # type: ignore[import-not-found]
    except ImportError:
        pass
    else:
        detector = _lingua_detector(LanguageDetectorBuilder)
        detected = detector.detect_language_of(text)  # type: ignore[attr-defined]
        if detected is not None:
            return LanguageGuess(detected.iso_code_639_1.name.lower(), 0.95, "lingua")

    script = _script_of(text)
    if script == "CYRILLIC":
        return _detect_cyrillic(text)
    if script == "ARABIC":
        return LanguageGuess("ar", 0.9, "script")
    if script == "HEBREW":
        return LanguageGuess("he", 0.9, "script")
    if script in ("HIRAGANA", "KATAKANA"):
        return LanguageGuess("ja", 0.9, "script")
    if script == "CJK":
        # Han senza kana: cinese (il giapponese di solito contiene kana).
        return LanguageGuess("zh", 0.7, "script")
    if script == "DEVANAGARI":
        return LanguageGuess("hi", 0.8, "script")
    if script == "HANGUL":
        return LanguageGuess("ko", 0.9, "script")
    if script == "GREEK":
        return LanguageGuess("el", 0.9, "script")
    if script != "LATIN":
        return LanguageGuess(None, 0.0, "unknown-script")

    words = [w.lower() for w in _WORD_RE.findall(text)]
    if not words:
        return LanguageGuess(None, 0.0, "no-words")
    scores = {
        lang: sum(1 for w in words if w in stopwords) / len(words)
        for lang, stopwords in _STOPWORDS.items()
    }
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best_lang, best_score = ranked[0]
    margin = best_score - ranked[1][1]
    if best_score < _MIN_SCORE or margin < _MIN_MARGIN:
        return LanguageGuess(None, best_score, "stopwords-inconclusive")
    return LanguageGuess(best_lang, min(0.99, best_score * 3), "stopwords")


_cached_detector = None


def _lingua_detector(builder_cls: object) -> object:  # pragma: no cover - solo con extra [ml]
    global _cached_detector
    if _cached_detector is None:
        _cached_detector = builder_cls.from_all_spoken_languages().build()  # type: ignore[attr-defined]
    return _cached_detector

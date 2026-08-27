"""Conteggio del lessico di framing (data/lexicon_it.yaml, data/lexicon_en.yaml).

Ogni gruppo raccoglie termini con la stessa denotazione e connotazione diversa;
qui si contano le occorrenze per termine (confini di parola, case-insensitive)
nel testo di un articolo. L'aggregazione per fonte avviene in core/bias/framing.py.
Il file del lessico è pubblico e cresce via pull request: ogni voce ha
motivazione e paternità.
"""

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from core.config import DATA_DIR

METHOD_NAME = "framing-lexicon-v1"


def _word_variants(word: str) -> list[str]:
    """Varianti flessive elementari (it: clandestino->clandestini, tassa->tasse).

    Volutamente minimale e dichiarato: niente stemming aggressivo, solo le
    alternanze finali regolari di singolare/plurale italiane e il plurale in -s
    inglese. Ogni falso positivo è ispezionabile perché il lessico è pubblico.
    """
    variants = {word}
    if len(word) > 3:
        if word.endswith("o"):
            variants.add(word[:-1] + "i")
        elif word.endswith("a"):
            variants.add(word[:-1] + "e")
        elif word.endswith("e"):
            variants.add(word[:-1] + "i")
        if not word.endswith("s"):
            variants.add(word + "s")
    return sorted(variants)


def _term_pattern(term: str) -> re.Pattern[str]:
    words = term.lower().split()
    parts = []
    for word in words:
        alternatives = "|".join(re.escape(v) for v in _word_variants(word))
        parts.append(f"(?:{alternatives})")
    joined = r"\s+".join(parts)
    return re.compile(rf"(?<!\w)(?:{joined})(?!\w)", re.IGNORECASE)


@dataclass(frozen=True)
class LexiconTerm:
    term: str
    connotation: str
    note: str


@dataclass(frozen=True)
class LexiconGroup:
    id: str
    denotation: str
    topic: str
    rationale: str
    terms: tuple[LexiconTerm, ...]


def _lexicon_path(language: str) -> Path:
    return DATA_DIR / f"lexicon_{language}.yaml"


@lru_cache(maxsize=4)
def _compiled(
    language: str,
) -> tuple[tuple[LexiconGroup, ...], dict[str, dict[str, re.Pattern[str]]]]:
    path = _lexicon_path(language)
    if not path.exists():
        return (), {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    groups: list[LexiconGroup] = []
    patterns: dict[str, dict[str, re.Pattern[str]]] = {}
    for item in raw.get("groups", []):
        terms = tuple(
            LexiconTerm(
                term=str(t["term"]).strip(),
                connotation=str(t.get("connotation", "neutro")),
                note=str(t.get("note", "")),
            )
            for t in item.get("terms", [])
        )
        group = LexiconGroup(
            id=item["id"],
            denotation=item.get("denotation", ""),
            topic=item.get("topic", ""),
            rationale=item.get("rationale", ""),
            terms=terms,
        )
        groups.append(group)
        patterns[group.id] = {t.term: _term_pattern(t.term) for t in terms}
    return tuple(groups), patterns


def load_groups(language: str) -> tuple[LexiconGroup, ...]:
    return _compiled(language)[0]


def count_terms(text: str, language: str | None) -> dict[str, dict[str, int]]:
    """{gruppo: {termine: occorrenze}} per i soli gruppi con almeno un'occorrenza."""
    if language not in ("it", "en"):
        return {}
    _groups, patterns = _compiled(language)
    result: dict[str, dict[str, int]] = {}
    for group_id, term_patterns in patterns.items():
        counts = {
            term: len(pattern.findall(text))
            for term, pattern in term_patterns.items()
        }
        counts = {term: n for term, n in counts.items() if n > 0}
        if counts:
            result[group_id] = counts
    return result

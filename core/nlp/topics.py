"""Classificazione a tassonomia fissa (data/topics.yaml), senza modelli.

Metodo "keyword-taxonomy-v1": conteggio di parole chiave discriminanti per
tema, con confini di parola, nella lingua dell'articolo (con riserva inglese).
È il livello base, sempre disponibile e ispezionabile: la lista di parole è
pubblica e modificabile via pull request. Il punteggio è la quota di keyword
distinte del tema trovate nel testo, quindi confrontabile tra temi.
"""

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from core.config import DATA_DIR

TOPICS_PATH = DATA_DIR / "topics.yaml"
METHOD_NAME = "keyword-taxonomy-v1"


@dataclass(frozen=True)
class Topic:
    id: str
    label_it: str
    label_en: str
    description: str


@dataclass(frozen=True)
class TopicScore:
    topic_id: str
    score: float
    hits: tuple[str, ...]


_Patterns = dict[str, dict[str, list[tuple[str, re.Pattern[str]]]]]


@lru_cache(maxsize=4)
def _compiled(path: str) -> tuple[list[Topic], _Patterns]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    topics: list[Topic] = []
    patterns: dict[str, dict[str, list[tuple[str, re.Pattern[str]]]]] = {}
    for item in raw["topics"]:
        topic = Topic(
            id=item["id"],
            label_it=item["label_it"],
            label_en=item["label_en"],
            description=item.get("description", ""),
        )
        topics.append(topic)
        per_lang: dict[str, list[tuple[str, re.Pattern[str]]]] = {}
        for lang, keywords in (item.get("keywords") or {}).items():
            compiled = []
            for keyword in keywords or []:
                kw = str(keyword).strip().lower()
                if not kw:
                    continue
                compiled.append(
                    (kw, re.compile(rf"(?<!\w){re.escape(kw)}(?!\w)", re.IGNORECASE))
                )
            per_lang[lang] = compiled
        patterns[topic.id] = per_lang
    return topics, patterns


def load_topics(path: Path = TOPICS_PATH) -> list[Topic]:
    return _compiled(str(path))[0]


def classify(
    text: str, language: str | None, path: Path = TOPICS_PATH
) -> list[TopicScore]:
    """Punteggi per tema, ordinati. Score = keyword distinte trovate / keyword del tema."""
    topics, patterns = _compiled(str(path))
    scores: list[TopicScore] = []
    for topic in topics:
        per_lang = patterns[topic.id]
        keywords = per_lang.get(language or "", [])
        if not keywords and language != "en":
            keywords = per_lang.get("en", [])
        if not keywords:
            continue
        hits = tuple(kw for kw, pattern in keywords if pattern.search(text))
        if hits:
            scores.append(
                TopicScore(topic.id, round(len(hits) / len(keywords), 4), hits)
            )
    scores.sort(key=lambda s: s.score, reverse=True)
    return scores


def primary_topic(text: str, language: str | None) -> TopicScore | None:
    scores = classify(text, language)
    return scores[0] if scores else None

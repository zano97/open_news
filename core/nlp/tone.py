"""Tono dei titoli con lessico di valenza (metodo "tone-lexicon-v1").

Regola di presentazione (metodologia §3): il tono è mostrato solo come
distribuzione per fonte (quota di titoli negativi/neutri/positivi), mai come
giudizio sul singolo articolo. Il lessico è pubblico in data/sentiment_*.yaml.
"""

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from core.config import DATA_DIR

METHOD_NAME = "tone-lexicon-v1"
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

_NEG_THRESHOLD = -0.5
_POS_THRESHOLD = 0.5


@dataclass(frozen=True)
class ToneScore:
    label: str  # negativo | neutro | positivo
    score: float
    matched: tuple[str, ...]


@lru_cache(maxsize=4)
def _valence(language: str) -> dict[str, float]:
    path = DATA_DIR / f"sentiment_{language}.yaml"
    if not path.exists():
        return {}
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return {str(k).lower(): float(v) for k, v in (raw.get("valence") or {}).items()}


def score_title(title: str, language: str | None) -> ToneScore:
    lang = language if language in ("it", "en") else "en"
    valence = _valence(lang)
    tokens = [t.lower() for t in _TOKEN_RE.findall(title)]
    matched = [t for t in tokens if t in valence]
    if not matched:
        return ToneScore("neutro", 0.0, ())
    total = sum(valence[t] for t in matched)
    score = total / len(matched)
    if score <= _NEG_THRESHOLD:
        label = "negativo"
    elif score >= _POS_THRESHOLD:
        label = "positivo"
    else:
        label = "neutro"
    return ToneScore(label, round(score, 3), tuple(matched))

"""Embedding dei titoli/snippet, con backend dichiarato nella provenance.

Due backend dietro la stessa interfaccia (ADR-0008):

- ``hashing`` (default): feature hashing con segno di parole piene (senza
  stopword) + 4/5-grammi di caratteri, L2-normalizzato. Deterministico,
  nessun download, nessuna rete. Buono nella stessa lingua; debole tra lingue
  diverse (le story cross-lingua si agganciano soprattutto tramite nomi propri).
- ``e5`` (extra ``[ml]``): ``intfloat/multilingual-e5-base`` via
  sentence-transformers. Multilingue, raccomandato in produzione.

La qualità della soglia di clustering per ciascun backend è misurata su
``data/seeds/calibration_pairs.yaml`` (vedi docs/METHODOLOGY.md §2).
"""

import hashlib
import math
import re
from collections import Counter
from typing import Protocol

from core.config import get_settings

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


class Embedder(Protocol):
    name: str
    dim: int

    def embed(self, text: str) -> list[float]: ...


def cosine(a: list[float], b: list[float]) -> float:
    """Similarità coseno; i vettori dei nostri backend sono già normalizzati."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class HashingEmbedder:
    """Feature hashing con segno: parole piene + 4/5-grammi di caratteri.

    Le stopword vengono escluse (il segnale è il lessico "pieno" condiviso);
    i 4/5-grammi di caratteri catturano flessioni e derivazioni
    ("approvato"/"approvazione"). Variante scelta sul set di calibrazione:
    F1 0.82 monolingua alla soglia 0.10 (vedi scripts/calibrate_threshold.py
    e docs/METHODOLOGY.md §2).
    """

    name = "hashing-ngram-v2"
    _CHAR_NGRAMS = (4, 5)

    def __init__(self, dim: int | None = None) -> None:
        self.dim = dim if dim is not None else get_settings().embedding_dim

    def _features(self, text: str) -> dict[str, float]:
        from core.extract.language import ALL_STOPWORDS

        tokens = [t.lower() for t in _TOKEN_RE.findall(text)]
        content = [t for t in tokens if t not in ALL_STOPWORDS]
        counts: Counter[str] = Counter(content)
        joined = " " + " ".join(content) + " "
        for size in self._CHAR_NGRAMS:
            for i in range(len(joined) - size + 1):
                counts[f"c:{joined[i : i + size]}"] += 1
        return {feature: 1.0 + math.log(count) for feature, count in counts.items()}

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        features = self._features(text)
        if not features:
            return vector
        for feature, weight in features.items():
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            value = int.from_bytes(digest, "big")
            index = value % self.dim
            sign = 1.0 if value >> 63 & 1 else -1.0
            vector[index] += sign * weight
        norm = math.sqrt(sum(x * x for x in vector))
        if norm > 0:
            vector = [x / norm for x in vector]
        return vector


class E5Embedder:  # pragma: no cover - richiede l'extra [ml] e il download del modello
    """intfloat/multilingual-e5-base via sentence-transformers (extra [ml])."""

    name = "e5-base-v1"

    def __init__(self) -> None:
        from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]

        self._model = SentenceTransformer("intfloat/multilingual-e5-base")
        self.dim = int(self._model.get_sentence_embedding_dimension() or 768)

    def embed(self, text: str) -> list[float]:
        # Il prefisso "query: "/"passage: " è parte del contratto d'uso di e5.
        vector = self._model.encode(f"passage: {text}", normalize_embeddings=True)
        return [float(x) for x in vector]


_embedder: Embedder | None = None


def get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        backend = get_settings().embedding_backend
        if backend == "e5":  # pragma: no cover - richiede l'extra [ml]
            _embedder = E5Embedder()
        else:
            _embedder = HashingEmbedder()
    return _embedder


def reset_embedder() -> None:
    """Per i test."""
    global _embedder
    _embedder = None

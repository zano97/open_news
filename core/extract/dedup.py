"""Dedup dei quasi-duplicati con SimHash a 64 bit, implementato in casa.

Un articolo ripubblicato con piccole modifiche (maiuscole, un'aggiunta breve,
parametri diversi nell'URL) produce un simhash a distanza di Hamming piccola.
La soglia di default (3 bit) è volutamente prudente: meglio un duplicato in
più che una notizia persa. Implementazione autonoma per evitare dipendenze
(vedi docs/DECISIONS.md, ADR-0011).
"""

import hashlib
import re
from collections import Counter

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

HASH_BITS = 64
DEFAULT_MAX_DISTANCE = 3


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _shingles(tokens: list[str], size: int = 2) -> list[str]:
    if len(tokens) < size:
        return [" ".join(tokens)] if tokens else []
    return [" ".join(tokens[i : i + size]) for i in range(len(tokens) - size + 1)]


def simhash64(text: str) -> int:
    """SimHash a 64 bit su shingle di 2 parole, pesati per frequenza."""
    weights = Counter(_shingles(_tokens(text)))
    if not weights:
        return 0
    bits = [0] * HASH_BITS
    for shingle, weight in weights.items():
        digest = hashlib.blake2b(shingle.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        for i in range(HASH_BITS):
            if value >> i & 1:
                bits[i] += weight
            else:
                bits[i] -= weight
    result = 0
    for i in range(HASH_BITS):
        if bits[i] > 0:
            result |= 1 << i
    return result


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def to_hex(value: int) -> str:
    return f"{value:016x}"


def from_hex(value: str) -> int:
    return int(value, 16)


def is_near_duplicate(a: int, b: int, max_distance: int = DEFAULT_MAX_DISTANCE) -> bool:
    return hamming(a, b) <= max_distance

"""Calibrazione della soglia di clustering su coppie annotate a mano.

Il set (data/seeds/calibration_pairs.yaml) contiene 100 coppie di titoli con
etichetta same_story annotata manualmente. Qui si calcola la similarità di
ogni coppia con il backend attivo e si misura precision/recall/F1 al variare
della soglia. I numeri finiscono in docs/METHODOLOGY.md §2 e il valore scelto
in Settings.cluster_similarity_threshold.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml

from core.config import DATA_DIR
from core.nlp.embed import Embedder, cosine

PAIRS_PATH = DATA_DIR / "seeds" / "calibration_pairs.yaml"


@dataclass(frozen=True)
class PairSample:
    id: str
    title_a: str
    title_b: str
    same_story: bool
    cross_language: bool


@dataclass(frozen=True)
class PairResult:
    sample: PairSample
    similarity: float

    def same_story_predicted(self, threshold: float) -> bool:
        return self.similarity >= threshold


@dataclass(frozen=True)
class ThresholdPoint:
    threshold: float
    precision: float
    recall: float
    f1: float
    true_positives: int
    false_positives: int
    false_negatives: int


def load_pairs(path: Path = PAIRS_PATH) -> list[PairSample]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [
        PairSample(
            id=p["id"],
            title_a=p["title_a"],
            title_b=p["title_b"],
            same_story=bool(p["same_story"]),
            cross_language=bool(p.get("cross_language", False)),
        )
        for p in raw["pairs"]
    ]


def evaluate_pairs(pairs: list[PairSample], embedder: Embedder) -> list[PairResult]:
    return [
        PairResult(p, cosine(embedder.embed(p.title_a), embedder.embed(p.title_b)))
        for p in pairs
    ]


def sweep(
    results: list[PairResult], thresholds: list[float] | None = None
) -> list[ThresholdPoint]:
    if thresholds is None:
        thresholds = [round(0.05 * i, 2) for i in range(1, 20)]
    points: list[ThresholdPoint] = []
    for threshold in thresholds:
        tp = sum(1 for r in results if r.same_story_predicted(threshold) and r.sample.same_story)
        fp = sum(
            1 for r in results if r.same_story_predicted(threshold) and not r.sample.same_story
        )
        fn = sum(
            1 for r in results if not r.same_story_predicted(threshold) and r.sample.same_story
        )
        precision = tp / (tp + fp) if tp + fp else 1.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        points.append(
            ThresholdPoint(threshold, precision, recall, f1, tp, fp, fn)
        )
    return points


def best_f1(points: list[ThresholdPoint]) -> ThresholdPoint:
    return max(points, key=lambda p: p.f1)

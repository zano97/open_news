"""Livello 4 — Posizionamento: giudizio umano con protocollo dichiarato.

- Krippendorff's alpha (metrica ordinale) implementato in casa e testato.
- Regole di pubblicazione (metodologia §4): un'etichetta per fonte esce solo
  con >= `annotation_min_articles` articoli annotati, >= `annotation_min_annotators`
  annotatori con orientamenti dichiarati DIVERSI (almeno due fasce), e
  alpha >= `annotation_min_alpha`. Altrimenti: "in valutazione (n/50, k annotatori)".
- Pesatura: le annotazioni sono pesate in modo che ogni fascia di orientamento
  dichiarato pesi ugualmente (una fascia numerosa non domina la media).
"""

import logging
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.bias.signals import write_signal
from core.config import get_settings
from core.models import Annotation, AnnotatorProfile, Article, Source, utcnow

log = logging.getLogger(__name__)

METHOD_NAME = "annotation-protocol-v1"
AXES = ("economic", "cultural")

# Fasce di orientamento dichiarato (per asse): il protocollo richiede che gli
# annotatori non appartengano tutti alla stessa fascia.
_BUCKET_EDGES = (-0.5, 0.5)


def orientation_bucket(value: float) -> str:
    if value < _BUCKET_EDGES[0]:
        return "meno"
    if value > _BUCKET_EDGES[1]:
        return "piu"
    return "centro"


def krippendorff_alpha_ordinal(
    ratings: dict[int, dict[int, int]], categories: list[int] | None = None
) -> float | None:
    """Alpha di Krippendorff con metrica ordinale.

    `ratings`: {unità: {codificatore: valore}}. Ritorna None se non ci sono
    abbastanza dati (nessuna unità con almeno due giudizi).
    """
    if categories is None:
        categories = [-2, -1, 0, 1, 2]
    cat_index = {c: i for i, c in enumerate(categories)}
    k = len(categories)

    # Matrice di coincidenza: coppie di valori dentro la stessa unità.
    coincidence = [[0.0] * k for _ in range(k)]
    for unit_ratings in ratings.values():
        values = [v for v in unit_ratings.values() if v in cat_index]
        m = len(values)
        if m < 2:
            continue
        for i, vi in enumerate(values):
            for j, vj in enumerate(values):
                if i != j:
                    coincidence[cat_index[vi]][cat_index[vj]] += 1.0 / (m - 1)

    n_c = [sum(row) for row in coincidence]
    n_total = sum(n_c)
    if n_total <= 1:
        return None

    # Distanza ordinale al quadrato tra le categorie c e d:
    # (somma delle frequenze marginali tra c e d, meno le metà agli estremi)^2.
    def delta2(c: int, d: int) -> float:
        if c == d:
            return 0.0
        lo, hi = min(c, d), max(c, d)
        cumulative = sum(n_c[g] for g in range(lo, hi + 1)) - (n_c[lo] + n_c[hi]) / 2
        return cumulative**2

    observed = sum(
        coincidence[c][d] * delta2(c, d) for c in range(k) for d in range(k)
    )
    expected = sum(
        n_c[c] * n_c[d] * delta2(c, d) for c in range(k) for d in range(k) if c != d
    ) / (n_total - 1)
    if expected == 0:
        # Nessuna variabilità attesa: accordo perfetto per definizione.
        return 1.0
    return 1.0 - observed / expected


async def _source_annotations(
    session: AsyncSession, source_id: int, axis: str, window_days: int | None = None
) -> list[tuple[Annotation, AnnotatorProfile]]:
    query = (
        select(Annotation, AnnotatorProfile)
        .join(AnnotatorProfile, Annotation.annotator_id == AnnotatorProfile.id)
        .join(Article, Annotation.article_id == Article.id)
        .where(
            Article.source_id == source_id,
            Annotation.axis == axis,
            Annotation.not_applicable.is_(False),
            Annotation.value.is_not(None),
        )
    )
    if window_days is not None:
        query = query.where(
            Annotation.created_at >= utcnow() - timedelta(days=window_days)
        )
    return [(a, p) for a, p in (await session.execute(query)).all()]


def _declared(profile: AnnotatorProfile, axis: str) -> float:
    return (
        profile.self_axis_economic if axis == "economic" else profile.self_axis_cultural
    )


async def aggregate_source_annotation(
    session: AsyncSession, source: Source, axis: str
) -> dict[str, object]:
    """Etichetta (o stato "in valutazione") per una fonte su un asse."""
    settings = get_settings()
    rows = await _source_annotations(session, source.id, axis)

    articles = {a.article_id for a, _ in rows}
    annotators = {p.id: p for _, p in rows}
    buckets = {orientation_bucket(_declared(p, axis)) for p in annotators.values()}

    ratings: dict[int, dict[int, int]] = defaultdict(dict)
    for a, p in rows:
        if a.value is not None:
            ratings[a.article_id][p.id] = a.value
    alpha = krippendorff_alpha_ordinal(dict(ratings))

    missing: list[str] = []
    if len(articles) < settings.annotation_min_articles:
        missing.append(
            f"articoli annotati {len(articles)}/{settings.annotation_min_articles}"
        )
    if len(annotators) < settings.annotation_min_annotators:
        missing.append(
            f"annotatori {len(annotators)}/{settings.annotation_min_annotators}"
        )
    if len(buckets) < 2:
        missing.append("serve almeno una seconda fascia di orientamento dichiarato")
    if alpha is None:
        missing.append("accordo non calcolabile (servono articoli con più giudizi)")
    elif alpha < settings.annotation_min_alpha:
        missing.append(
            f"accordo α={alpha:.2f} sotto la soglia {settings.annotation_min_alpha}"
        )

    base: dict[str, object] = {
        "axis": axis,
        "n_articles": len(articles),
        "n_annotators": len(annotators),
        "alpha": round(alpha, 3) if alpha is not None else None,
        "buckets": sorted(buckets),
    }
    if missing:
        return {**base, "status": "in valutazione", "missing": missing}

    # Media pesata: ogni fascia di orientamento pesa ugualmente.
    per_bucket: dict[str, list[int]] = defaultdict(list)
    for a, p in rows:
        if a.value is not None:
            per_bucket[orientation_bucket(_declared(p, axis))].append(a.value)
    bucket_means = {b: sum(v) / len(v) for b, v in per_bucket.items()}
    label = sum(bucket_means.values()) / len(bucket_means)
    return {
        **base,
        "status": "pubblicata",
        "label": round(label, 2),
        "bucket_means": {b: round(m, 2) for b, m in bucket_means.items()},
    }


async def compute_annotation_signals(session: AsyncSession) -> int:
    """Segnale `annotation` per ogni fonte/asse con almeno un'annotazione."""
    until = utcnow()
    source_ids = set(
        (
            await session.execute(
                select(Article.source_id)
                .join(Annotation, Annotation.article_id == Article.id)
                .distinct()
            )
        ).scalars()
    )
    written = 0
    for sid in source_ids:
        source = (
            await session.execute(select(Source).where(Source.id == sid))
        ).scalar_one()
        for axis in AXES:
            value = await aggregate_source_annotation(session, source, axis)
            await write_signal(
                session,
                source_id=sid,
                signal_type="annotation",
                axis=axis,
                period_start=(until - timedelta(days=365)).date(),
                period_end=until.date(),
                value=value,
                n_articles=n_arts if isinstance(n_arts := value.get("n_articles", 0), int) else 0,
                method=METHOD_NAME,
                inputs={
                    "min_articles": get_settings().annotation_min_articles,
                    "min_annotators": get_settings().annotation_min_annotators,
                    "min_alpha": get_settings().annotation_min_alpha,
                },
            )
            written += 1
    return written

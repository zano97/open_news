"""Addestramento opzionale del classificatore di posizionamento (livello 4).

Regole non negoziabili (metodologia §4):
- si addestra SOLO su annotazioni umane raccolte con il protocollo cieco;
- le predizioni del modello si usano SOLO aggregate per fonte, mai sul
  singolo articolo, e sono sempre marcate "stima automatica" con
  l'accuratezza sul test set mostrata accanto.

Richiede gli extra [ml] (sentence-transformers, scikit-learn). Senza,
esporta comunque il dataset di addestramento in JSONL e si ferma.
"""

import asyncio
import json
from collections import defaultdict
from pathlib import Path

from sqlalchemy import select

from core.config import DATA_DIR
from core.db import get_sessionmaker
from core.models import Annotation, Article

EXPORT_PATH = DATA_DIR / "cache" / "training_positioning.jsonl"
MODEL_PATH = DATA_DIR / "cache" / "positioning_model.joblib"
MIN_EXAMPLES = 200


async def export_dataset() -> list[dict[str, object]]:
    maker = get_sessionmaker()
    async with maker() as session:
        rows = (
            await session.execute(
                select(Annotation, Article)
                .join(Article, Annotation.article_id == Article.id)
                .where(Annotation.value.is_not(None))
            )
        ).all()
    per_article: dict[int, dict[str, object]] = {}
    sums: dict[tuple[int, str], list[int]] = defaultdict(list)
    for annotation, article in rows:
        per_article[article.id] = {
            "article_id": article.id,
            "text": f"{article.title}. {article.snippet}".strip(),
        }
        if annotation.value is not None:
            sums[(article.id, annotation.axis)].append(annotation.value)
    examples = []
    for article_id, payload in per_article.items():
        labels = {
            axis: sum(v) / len(v)
            for (aid, axis), v in sums.items()
            if aid == article_id and v
        }
        if labels:
            examples.append({**payload, "labels": labels})
    EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with EXPORT_PATH.open("w", encoding="utf-8") as fh:
        for example in examples:
            fh.write(json.dumps(example, ensure_ascii=False) + "\n")
    print(f"dataset esportato: {EXPORT_PATH} ({len(examples)} esempi)")
    return examples


def train(examples: list[dict[str, object]]) -> None:
    try:
        import joblib  # type: ignore[import-not-found]
        import numpy as np
        from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]
        from sklearn.linear_model import Ridge  # type: ignore[import-not-found]
        from sklearn.model_selection import cross_val_score  # type: ignore[import-not-found]
    except ImportError:
        print(
            "Extra [ml] non installati (sentence-transformers, scikit-learn): "
            "mi fermo dopo l'export. Installa con: pip install -e '.[ml]' joblib scikit-learn"
        )
        return

    if len(examples) < MIN_EXAMPLES:
        print(
            f"Servono almeno {MIN_EXAMPLES} esempi annotati (ora: {len(examples)}): "
            "il modello non viene addestrato per non pubblicare stime deboli."
        )
        return

    model = SentenceTransformer("intfloat/multilingual-e5-base")
    texts = [str(e["text"]) for e in examples]
    embeddings = model.encode([f"query: {t}" for t in texts], normalize_embeddings=True)

    bundle: dict[str, object] = {"encoder": "intfloat/multilingual-e5-base"}
    for axis in ("economic", "cultural"):
        pairs = [
            (embeddings[i], float(e["labels"][axis]))  # type: ignore[index,call-overload]
            for i, e in enumerate(examples)
            if axis in e["labels"]  # type: ignore[operator]
        ]
        if len(pairs) < MIN_EXAMPLES:
            print(f"asse {axis}: esempi insufficienti ({len(pairs)}), salto")
            continue
        x = np.array([p[0] for p in pairs])
        y = np.array([p[1] for p in pairs])
        regressor = Ridge(alpha=1.0)
        scores = cross_val_score(
            regressor, x, y, cv=5, scoring="neg_mean_absolute_error"
        )
        mae = -scores.mean()
        regressor.fit(x, y)
        bundle[axis] = {"model": regressor, "cv_mae": float(mae), "n": len(pairs)}
        print(f"asse {axis}: MAE cross-validation = {mae:.3f} su {len(pairs)} esempi")

    joblib.dump(bundle, MODEL_PATH)
    print(
        f"modello salvato in {MODEL_PATH}. Le predizioni vanno usate SOLO "
        "aggregate per fonte e marcate 'stima automatica' con il MAE accanto."
    )


def main() -> None:
    examples = asyncio.run(export_dataset())
    train(examples)


if __name__ == "__main__":
    main()

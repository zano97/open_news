"""Calibra la soglia di clustering sul set di 100 coppie annotate a mano.

Uso: `.venv/bin/python -m scripts.calibrate_threshold`
Stampa precision/recall/F1 per soglia (tutte le coppie e solo monolingua)
con il backend di embedding attivo (EMBEDDING_BACKEND). I risultati vanno
riportati in docs/METHODOLOGY.md quando si cambia backend o set.
"""

from core.cluster.calibrate import best_f1, evaluate_pairs, load_pairs, sweep
from core.config import get_settings
from core.nlp.embed import get_embedder


def main() -> None:
    embedder = get_embedder()
    pairs = load_pairs()
    results = evaluate_pairs(pairs, embedder)
    mono = [r for r in results if not r.sample.cross_language]
    cross = [r for r in results if r.sample.cross_language]

    print(f"Backend: {embedder.name} — {len(pairs)} coppie "
          f"({len(mono)} monolingua, {len(cross)} cross-lingua)\n")

    for label, subset in (("TUTTE LE COPPIE", results), ("SOLO MONOLINGUA", mono)):
        points = sweep(subset)
        print(f"== {label} ==")
        print(f"{'soglia':>7} {'prec':>6} {'rec':>6} {'F1':>6}   tp/fp/fn")
        for p in points:
            marker = " <== migliore F1" if p == best_f1(points) else ""
            print(
                f"{p.threshold:>7.2f} {p.precision:>6.2f} {p.recall:>6.2f} "
                f"{p.f1:>6.2f}   {p.true_positives}/{p.false_positives}/{p.false_negatives}"
                f"{marker}"
            )
        print()

    best_mono = best_f1(sweep(mono))
    configured = get_settings().cluster_similarity_threshold
    print(
        f"Migliore soglia (monolingua): {best_mono.threshold:.2f} "
        f"(F1={best_mono.f1:.2f}) — soglia configurata: {configured:.2f}"
    )


if __name__ == "__main__":
    main()

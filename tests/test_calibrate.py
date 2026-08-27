"""Fase 2: la soglia di clustering è calibrata e documentata, non arbitraria.

Il set di 100 coppie annotate a mano (data/seeds/calibration_pairs.yaml) è la
verità di riferimento: questi test tengono onesta la soglia di default e la
qualità del backend hashing. Se si cambia embedder o set, la calibrazione va
rifatta (scripts/calibrate_threshold.py) e questi numeri aggiornati insieme a
docs/METHODOLOGY.md.
"""

from core.cluster.calibrate import best_f1, evaluate_pairs, load_pairs, sweep
from core.config import get_settings
from core.nlp.embed import HashingEmbedder


def test_set_di_calibrazione_completo() -> None:
    pairs = load_pairs()
    assert len(pairs) == 100
    positivi = [p for p in pairs if p.same_story]
    assert len(positivi) == 50
    cross = [p for p in pairs if p.cross_language]
    assert len(cross) >= 15


def test_qualita_backend_hashing_monolingua() -> None:
    pairs = [p for p in load_pairs() if not p.cross_language]
    results = evaluate_pairs(pairs, HashingEmbedder())
    migliore = best_f1(sweep(results))
    assert migliore.f1 >= 0.75, (
        f"la qualità del backend hashing è degradata: F1={migliore.f1:.2f}"
    )


def test_soglia_configurata_vicina_all_ottimo() -> None:
    pairs = [p for p in load_pairs() if not p.cross_language]
    results = evaluate_pairs(pairs, HashingEmbedder())
    configurata = get_settings().cluster_similarity_threshold
    punti = sweep(results, [configurata])
    assert punti[0].precision >= 0.7, punti[0]
    assert punti[0].recall >= 0.7, punti[0]

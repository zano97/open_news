"""Fase 4: temi, tono, lessico di framing, attori citati (unità)."""

import yaml

from core.config import DATA_DIR
from core.nlp.actors import extract_citations
from core.nlp.lexicon import count_terms, load_groups
from core.nlp.tone import score_title
from core.nlp.topics import classify, load_topics, primary_topic


class TestTopics:
    def test_tassonomia_di_20_temi(self) -> None:
        topics = load_topics()
        assert len(topics) == 20
        assert all(t.label_it for t in topics)

    def test_titolo_immigrazione(self) -> None:
        # Usa una keyword reale della tassonomia, così il test segue il file.
        raw = yaml.safe_load((DATA_DIR / "topics.yaml").read_text())
        keywords = next(
            t["keywords"]["it"] for t in raw["topics"] if t["id"] == "immigrazione"
        )
        titolo = f"Nuovo record di {keywords[0]} nel canale di Sicilia"
        top = primary_topic(titolo, "it")
        assert top is not None
        assert top.topic_id == "immigrazione"

    def test_lingua_non_coperta_usa_inglese(self) -> None:
        raw = yaml.safe_load((DATA_DIR / "topics.yaml").read_text())
        keywords = next(
            t["keywords"]["en"] for t in raw["topics"] if t["id"] == "clima_ambiente"
        )
        titolo = f"New report on {keywords[0]} published today"
        scores = classify(titolo, "sv")  # svedese: non nel file, riserva inglese
        assert scores
        assert scores[0].topic_id == "clima_ambiente"

    def test_nessun_tema(self) -> None:
        assert classify("xyzzy qwerty", "it") == []


class TestTone:
    def test_titolo_negativo(self) -> None:
        tono = score_title("Strage sul lavoro: tre morti nel crollo del cantiere", "it")
        assert tono.label == "negativo"
        assert tono.matched

    def test_titolo_positivo(self) -> None:
        tono = score_title("Storica vittoria: accordo di pace firmato", "it")
        assert tono.label == "positivo"

    def test_titolo_neutro(self) -> None:
        tono = score_title("Il consiglio comunale approva il bilancio? Riunione domani", "en")
        assert tono.label in ("neutro", "positivo")  # nessuna parola forte

    def test_lingua_sconosciuta_usa_inglese(self) -> None:
        tono = score_title("War and crisis everywhere", "de")
        assert tono.label == "negativo"


class TestLexicon:
    def test_gruppi_caricati(self) -> None:
        gruppi_it = load_groups("it")
        assert len(gruppi_it) >= 40
        gruppi_en = load_groups("en")
        assert len(gruppi_en) >= 20
        for gruppo in gruppi_it:
            assert gruppo.rationale, f"{gruppo.id} senza motivazione"
            assert len(gruppo.terms) >= 2

    def test_flessione_semplice(self) -> None:
        # Il lessico registra "clandestino": il plurale nei titoli deve contare.
        counts = count_terms("Nuovo sbarco di clandestini nella notte", "it")
        gruppi_colpiti = set(counts)
        assert any("clandestin" in str(counts[g]) for g in gruppi_colpiti)

    def test_lingua_non_coperta(self) -> None:
        assert count_terms("texte en français", "fr") == {}

    def test_multi_parola(self) -> None:
        counts = count_terms(
            "Il dibattito sull'utero in affitto divide il parlamento", "it"
        )
        assert counts, "il termine multi-parola deve essere riconosciuto"


class TestActors:
    TESTO = (
        'Il ministro dell\'Economia Mario Rossi ha detto: «La manovra non cambierà». '
        '«Serve più coraggio», ha dichiarato Paola Bianchi, economista '
        "dell'università di Bologna. Secondo Luca Verdi, residente del quartiere, "
        "la situazione è insostenibile."
    )

    def test_estrazione_parlanti(self) -> None:
        citazioni = extract_citations(self.TESTO)
        parlanti = {c.speaker for c in citazioni}
        assert "Mario Rossi" in parlanti
        assert "Paola Bianchi" in parlanti

    def test_ruoli(self) -> None:
        citazioni = {c.speaker: c for c in extract_citations(self.TESTO)}
        assert citazioni["Mario Rossi"].role == "governo"
        assert citazioni["Paola Bianchi"].role == "esperto"

    def test_testo_senza_citazioni(self) -> None:
        assert extract_citations("il tempo domani sarà sereno su tutta la penisola") == []

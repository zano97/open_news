"""Fase 1: canonicalizzazione URL, simhash, lingua, snippet, testo integrale."""

from core.extract.canonical import canonicalize
from core.extract.dedup import (
    from_hex,
    hamming,
    is_near_duplicate,
    simhash64,
    to_hex,
)
from core.extract.fulltext import extract_text
from core.extract.language import detect_language
from core.ingest.rss import make_snippet


class TestCanonical:
    def test_rimuove_parametri_di_tracking(self) -> None:
        url = "https://Esempio.test/articolo?utm_source=rss&utm_medium=feed&id=5&fbclid=abc"
        assert canonicalize(url) == "https://esempio.test/articolo?id=5"

    def test_rimuove_frammento_e_ordina_query(self) -> None:
        assert (
            canonicalize("https://esempio.test/a?b=2&a=1#sezione")
            == "https://esempio.test/a?a=1&b=2"
        )

    def test_stesso_articolo_da_campagne_diverse(self) -> None:
        a = canonicalize("https://esempio.test/x?utm_campaign=social")
        b = canonicalize("https://esempio.test/x?utm_source=rss")
        assert a == b == "https://esempio.test/x"

    def test_porta_non_standard_conservata(self) -> None:
        assert canonicalize("http://esempio.test:8080/a") == "http://esempio.test:8080/a"


class TestSimhash:
    TESTO = (
        "Dopo mesi di trattative con i sindacati, il consiglio dei ministri "
        "ha approvato la riforma delle pensioni per i lavoratori del settore privato"
    )

    def test_identico_distanza_zero(self) -> None:
        assert hamming(simhash64(self.TESTO), simhash64(self.TESTO)) == 0

    def test_quasi_identico_distanza_piccola(self) -> None:
        modificato = self.TESTO.replace("privato", "pubblico")
        assert is_near_duplicate(simhash64(self.TESTO), simhash64(modificato), 12)

    def test_testi_diversi_distanza_grande(self) -> None:
        altro = (
            "La squadra vince il campionato dopo una stagione straordinaria "
            "davanti ai propri tifosi nello stadio esaurito in ogni ordine di posti"
        )
        assert hamming(simhash64(self.TESTO), simhash64(altro)) > 12

    def test_hex_roundtrip(self) -> None:
        h = simhash64(self.TESTO)
        assert from_hex(to_hex(h)) == h
        assert len(to_hex(h)) == 16

    def test_testo_vuoto(self) -> None:
        assert simhash64("") == 0


class TestLanguage:
    def test_italiano(self) -> None:
        guess = detect_language(
            "Il consiglio dei ministri ha approvato la riforma delle pensioni "
            "dopo mesi di trattative con i sindacati"
        )
        assert guess.language == "it"

    def test_inglese(self) -> None:
        guess = detect_language(
            "The government has approved the pension reform after months of "
            "negotiations with the unions"
        )
        assert guess.language == "en"

    def test_francese(self) -> None:
        guess = detect_language(
            "Le gouvernement a approuvé la réforme des retraites après des mois "
            "de négociations avec les syndicats"
        )
        assert guess.language == "fr"

    def test_tedesco(self) -> None:
        guess = detect_language(
            "Die Regierung hat die Rentenreform nach monatelangen Verhandlungen "
            "mit den Gewerkschaften verabschiedet"
        )
        assert guess.language == "de"

    def test_spagnolo(self) -> None:
        guess = detect_language(
            "El gobierno ha aprobado la reforma de las pensiones tras meses de "
            "negociaciones con los sindicatos"
        )
        assert guess.language == "es"

    def test_ucraino_vs_russo(self) -> None:
        assert (
            detect_language("Уряд ухвалив пенсійну реформу після місяців переговорів").language
            == "uk"
        )
        assert detect_language("Правительство утвердило пенсионную реформу").language == "ru"

    def test_giapponese(self) -> None:
        assert (
            detect_language("政府は年金改革を承認しました。これは重要なニュースです").language
            == "ja"
        )

    def test_vuoto(self) -> None:
        assert detect_language("  ").language is None


class TestSnippet:
    def test_html_rimosso_ed_entita_decodificate(self) -> None:
        assert make_snippet("<p>Testo &egrave; <b>importante</b></p>") == "Testo è importante"

    def test_troncato_a_parola_con_ellissi(self) -> None:
        lungo = "parola " * 60
        snippet = make_snippet(lungo)
        assert len(snippet) <= 200
        assert snippet.endswith("…")
        assert not snippet[:-1].endswith(" ")

    def test_vuoto(self) -> None:
        assert make_snippet(None) == ""
        assert make_snippet("") == ""


class TestFulltext:
    def test_estrazione_da_html_semplice(self) -> None:
        html = """
        <html><head><title>Titolo pagina</title></head><body>
        <nav>menu menu menu</nav>
        <article><h1>Il titolo dell'articolo</h1>
        <p>Questo è il primo paragrafo dell'articolo, con un contenuto
        sufficientemente lungo perché l'estrattore lo riconosca come testo
        principale della pagina e non come rumore di navigazione.</p>
        <p>Secondo paragrafo con altre informazioni rilevanti sul tema
        trattato, per dare corpo al contenuto della pagina di prova.</p>
        </article>
        <footer>piè di pagina</footer>
        </body></html>
        """
        testo = extract_text(html, url="https://esempio.test/articolo")
        assert testo is not None
        assert "primo paragrafo" in testo
        assert "menu menu" not in testo

    def test_html_senza_contenuto(self) -> None:
        assert extract_text("<html><body></body></html>") is None

"""Traduzione automatica dei titoli neutri: marcata, con provenance, opzionale."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core import provenance
from core.models import Article, Source, Story
from core.nlp.translate import (
    display_title,
    set_translator,
    translate_story_title,
)

ORA = datetime(2026, 8, 27, 9, 0, tzinfo=UTC)


class TraduttoreFinto:
    """Backend di prova: traduce solo it->en, con prefisso riconoscibile."""

    name = "traduttore-finto-v1"

    def available_pairs(self) -> set[tuple[str, str]]:
        return {("it", "en")}

    def translate(self, text: str, source: str, target: str) -> str | None:
        if (source, target) != ("it", "en"):
            return None
        return f"[EN] {text}"


@pytest.fixture
def traduttore() -> TraduttoreFinto:
    fake = TraduttoreFinto()
    set_translator(fake)
    yield fake
    set_translator(None)


async def _story_italiana(session: AsyncSession) -> Story:
    fonte = Source(
        slug="trad-it", name="Gazzetta Trad", domain="trad.test", country="it",
        language="it", region="italy", feed_urls=[], terms_note="",
    )
    session.add(fonte)
    await session.flush()
    story = Story(
        title_neutral="Il governo approva la riforma delle pensioni",
        first_seen=ORA, last_seen=ORA + timedelta(minutes=30),
        article_count=1, source_count=1,
    )
    session.add(story)
    await session.flush()
    session.add(
        Article(
            source_id=fonte.id, url="https://trad.test/1",
            title="Il governo approva la riforma delle pensioni",
            language="it", story_id=story.id,
        )
    )
    await session.flush()
    await session.refresh(story)
    return story


async def test_traduzione_salvata_e_tracciata(
    session: AsyncSession, traduttore: TraduttoreFinto
) -> None:
    story = await _story_italiana(session)
    added = await translate_story_title(session, story)
    assert added == 1  # solo it->en è disponibile nel finto backend
    assert story.title_translations["en"] == (
        "[EN] Il governo approva la riforma delle pensioni"
    )
    prova = await provenance.for_entity(session, "story", story.id)
    riga = next(p for p in prova if p.field == "title_translations")
    assert riga.method == "traduttore-finto-v1"
    assert riga.inputs["source"] == "it"

    # Idempotente: la seconda esecuzione non ritraduce.
    assert await translate_story_title(session, story) == 0


async def test_senza_traduttore_nessun_effetto(session: AsyncSession) -> None:
    set_translator(None)
    story = await _story_italiana(session)
    assert await translate_story_title(session, story) == 0
    assert story.title_translations == {}


def test_display_title() -> None:
    story = Story(
        title_neutral="Titolo originale",
        title_translations={"en": "Translated headline"},
    )
    assert display_title(story, "en") == ("Translated headline", True)
    assert display_title(story, "it") == ("Titolo originale", False)
    assert display_title(story, "fr") == ("Titolo originale", False)


async def test_ui_mostra_traduzione_marcata(
    client: AsyncClient, session: AsyncSession
) -> None:
    story = await _story_italiana(session)
    story.title_translations = {"en": "Government approves pension reform"}
    await session.commit()

    # Interfaccia inglese: titolo ORIGINALE, traduzione tra parentesi, marcata.
    pagina = await client.get(f"/storia/{story.id}?lang=en")
    assert "Il governo approva la riforma delle pensioni" in pagina.text
    assert "(Government approves pension reform)" in pagina.text
    assert "automatic translation" in pagina.text

    prima = await client.get("/?lang=en")
    assert "(Government approves pension reform)" in prima.text
    assert "transl." in prima.text

    # Interfaccia italiana: solo l'originale, nessuna riga tra parentesi.
    it_pagina = await client.get(f"/storia/{story.id}")
    assert "Il governo approva la riforma delle pensioni" in it_pagina.text
    assert "titolo-traduzione" not in it_pagina.text


def test_sottotitolo_nella_lingua_del_lettore() -> None:
    from datetime import UTC, datetime

    from core.models import Article, Source, Story
    from core.nlp.translate import headline_subtitle

    def fonte(lingua: str) -> Source:
        return Source(
            slug=f"f-{lingua}", name="F", domain=f"{lingua}.test", country=lingua,
            language=lingua, region="world", feed_urls=[], terms_note="",
        )

    def articolo(titolo: str, lingua: str, ora: int, fonte_lingua: str | None = None) -> Article:
        a = Article(
            title=titolo, language=lingua, url=f"https://x.test/{lingua}/{ora}",
            published_at=datetime(2026, 8, 27, ora, tzinfo=UTC),
        )
        a.source = fonte(fonte_lingua or lingua)
        return a

    story = Story(title_neutral="Governo approva la riforma", title_translations={})
    story.articles = [
        articolo("Governo approva la riforma", "it", 9),
        articolo("Government passes the reform", "en", 10),
        articolo("Cabinet backs reform bill", "en", 8),
    ]

    # Titolo già nella lingua del lettore: nessun sottotitolo.
    assert headline_subtitle(story, "it") is None
    # Traduzione automatica assente: la versione IN LINGUA pubblicata prima
    # TRA QUELLE AGGANCIATE alla notizia ("Governo"/"Government" condividono
    # il prefisso; "Cabinet" no, e non è verificabile che sia la stessa).
    assert headline_subtitle(story, "en") == ("Government passes the reform", False)
    # La traduzione automatica, quando esiste, vince ed è marcata.
    story.title_translations = {"en": "Government approves the reform"}
    assert headline_subtitle(story, "en") == ("Government approves the reform", True)
    # Lingua senza versioni né traduzione: niente riga.
    assert headline_subtitle(story, "de") is None


def test_sottotitolo_non_si_fida_della_sola_lingua_rilevata() -> None:
    """Un titolo norvegese classificato per errore "it" NON deve diventare
    il sottotitolo italiano: serve la conferma della lingua della testata."""
    from datetime import UTC, datetime

    from core.models import Article, Source, Story
    from core.nlp.translate import headline_subtitle

    story = Story(title_neutral="Nepal flash floods", title_translations={})
    nrk = Article(
        title="Dødstallene stiger i Nepal", language="it",  # rilevazione SBAGLIATA
        url="https://nrk.test/x", published_at=datetime(2026, 8, 27, 8, tzinfo=UTC),
    )
    nrk.source = Source(
        slug="nrk", name="NRK", domain="nrk.test", country="no",
        language="no", region="europe", feed_urls=[], terms_note="",
    )
    inglese = Article(
        title="Nepal flash floods", language="en",
        url="https://bbc.test/x", published_at=datetime(2026, 8, 27, 9, tzinfo=UTC),
    )
    inglese.source = Source(
        slug="bbc", name="BBC", domain="bbc.test", country="gb",
        language="en", region="europe", feed_urls=[], terms_note="",
    )
    story.articles = [inglese, nrk]
    assert headline_subtitle(story, "it") is None  # meglio niente che sbagliato


def test_sottotitolo_preferisce_titoli_dal_feed() -> None:
    """A parità di lingua, il sottotitolo evita i titoli GDELT (senza
    snippet, apostrofi persi) se c'è una versione arrivata dal feed."""
    from datetime import UTC, datetime

    from core.models import Article, Source, Story
    from core.nlp.translate import headline_subtitle

    def fonte_it(slug: str) -> Source:
        return Source(
            slug=slug, name=slug, domain=f"{slug}.test", country="it",
            language="it", region="italy", feed_urls=[], terms_note="",
        )

    story = Story(title_neutral="Japanese artist dies at 97", title_translations={})
    via_gdelt = Article(
        title="Lartista è morta , addio alla regina dei pois", language="it",
        url="https://gd.test/1", snippet="",
        published_at=datetime(2026, 8, 27, 8, tzinfo=UTC),
    )
    via_gdelt.source = fonte_it("gd")
    dal_feed = Article(
        title="L'artista è morta, addio alla regina dei pois", language="it",
        url="https://feed.test/1", snippet="Il mondo dell'arte in lutto.",
        published_at=datetime(2026, 8, 27, 9, tzinfo=UTC),
    )
    dal_feed.source = fonte_it("feed")
    inglese = Article(
        title="Japanese artist dies at 97", language="en",
        url="https://en.test/1", snippet="x",
        published_at=datetime(2026, 8, 27, 7, tzinfo=UTC),
    )
    inglese.source = Source(
        slug="en", name="EN", domain="en.test", country="gb",
        language="en", region="europe", feed_urls=[], terms_note="",
    )
    story.articles = [inglese, via_gdelt, dal_feed]

    # Il titolo GDELT è più vecchio, ma vince la versione dal feed.
    assert headline_subtitle(story, "it") == (
        "L'artista è morta, addio alla regina dei pois", False
    )

def test_sottotitolo_mai_di_unaltra_notizia() -> None:
    """Un articolo finito nel cluster per errore NON deve diventare il
    sottotitolo: senza un nome proprio o numero in comune col titolo
    neutro, meglio nessuna riga (il caso reale: un liveticker tedesco
    sui dazi con sotto un titolo italiano sul caporalato a Milano)."""
    from datetime import UTC, datetime

    from core.models import Article, Source, Story
    from core.nlp.translate import headline_subtitle

    story = Story(
        title_neutral=(
            "Liveticker USA unter Trump: USA erhöhen Importmenge für Rindfleisch"
        ),
        title_translations={},
    )
    tedesco = Article(
        title=story.title_neutral, language="de",
        url="https://de.test/1", snippet="x",
        published_at=datetime(2026, 8, 27, 8, tzinfo=UTC),
    )
    tedesco.source = Source(
        slug="welt", name="W", domain="de.test", country="de",
        language="de", region="europe", feed_urls=[], terms_note="",
    )
    fuori_posto = Article(
        title=(
            "Caporalato a Milano, gli operai del cantiere del Consolato "
            "ora ricevono 11 euro all'ora"
        ),
        language="it", url="https://it.test/1", snippet="y",
        published_at=datetime(2026, 8, 27, 9, tzinfo=UTC),
    )
    fuori_posto.source = Source(
        slug="rep", name="R", domain="it.test", country="it",
        language="it", region="italy", feed_urls=[], terms_note="",
    )
    story.articles = [tedesco, fuori_posto]
    assert headline_subtitle(story, "it") is None

    # Con un aggancio vero (nome condiviso) la versione in lingua torna.
    agganciato = Article(
        title="Trump alza le quote di import di carne bovina negli USA",
        language="it", url="https://it.test/2", snippet="z",
        published_at=datetime(2026, 8, 27, 10, tzinfo=UTC),
    )
    agganciato.source = fuori_posto.source
    story.articles = [tedesco, fuori_posto, agganciato]
    assert headline_subtitle(story, "it") == (
        "Trump alza le quote di import di carne bovina negli USA", False
    )


class TraduttoreRegistratore:
    """Backend di prova che registra le chiamate (per contarle e ispezionarle)."""

    name = "registratore-v1"

    def __init__(self, esiti: dict[tuple[str, str], str | None]) -> None:
        self.esiti = esiti
        self.chiamate: list[tuple[str, str, str]] = []

    def available_pairs(self) -> set[tuple[str, str]]:
        return set(self.esiti)

    def translate(self, text: str, source: str, target: str) -> str | None:
        self.chiamate.append((text, source, target))
        return self.esiti.get((source, target))


async def test_lingua_sorgente_e_quella_del_titolo_neutro(
    session: AsyncSession,
) -> None:
    """Cluster a maggioranza italiana ma titolo neutro INGLESE: la sorgente
    giusta è l'inglese. Con quella sbagliata Argos restituiva testi identici
    o senza senso, scartati — e il titolo restava per sempre non tradotto."""
    from core.nlp.translate import neutral_title_language

    fonti = []
    for i, lingua in enumerate(["it", "it", "en"]):
        f = Source(
            slug=f"src-{i}", name=f"S{i}", domain=f"s{i}.test", country=lingua,
            language=lingua, region="world", feed_urls=[], terms_note="",
        )
        session.add(f)
        fonti.append(f)
    await session.flush()
    story = Story(
        title_neutral="Government approves the pension reform",
        first_seen=ORA, last_seen=ORA, article_count=3, source_count=3,
    )
    session.add(story)
    await session.flush()
    titoli = [
        ("Il governo approva la riforma", "it"),
        ("Pensioni, arriva la riforma", "it"),
        ("Government approves the pension reform", "en"),
    ]
    for i, (titolo, lingua) in enumerate(titoli):
        session.add(
            Article(
                source_id=fonti[i].id, url=f"https://s{i}.test/a",
                title=titolo, language=lingua, story_id=story.id,
            )
        )
    await session.flush()
    await session.refresh(story)

    assert neutral_title_language(story) == "en"

    finto = TraduttoreRegistratore({("en", "it"): "Il governo approva la riforma"})
    added = await translate_story_title(
        session, story, targets=("it",), translator=finto
    )
    assert added == 1
    assert story.title_translations["it"] == "Il governo approva la riforma"
    assert finto.chiamate[0][1:] == ("en", "it")


async def test_traduzione_identica_non_si_ritenta_per_sempre(
    session: AsyncSession,
) -> None:
    """Se Argos restituisce il testo uguale (nomi propri, coppia che non
    morde), si registra la sentinella vuota: la UI mostra l'originale e il
    giro dopo NON riprova lo stesso testo all'infinito."""
    story = await _story_italiana(session)
    finto = TraduttoreRegistratore({("it", "en"): story.title_neutral})
    added = await translate_story_title(
        session, story, targets=("en",), translator=finto
    )
    assert added == 1
    assert story.title_translations["en"] == ""  # sentinella
    assert display_title(story, "en") == (story.title_neutral, False)

    # Secondo giro: nessuna nuova chiamata al traduttore.
    prima = len(finto.chiamate)
    assert await translate_story_title(
        session, story, targets=("en",), translator=finto
    ) == 0
    assert len(finto.chiamate) == prima


async def test_coppia_mancante_registrata_negli_esiti(
    session: AsyncSession,
) -> None:
    from core.nlp.translate import LAST_ESITI, riepilogo_esiti

    LAST_ESITI.clear()
    story = await _story_italiana(session)
    finto = TraduttoreRegistratore({})  # nessuna coppia disponibile
    assert await translate_story_title(
        session, story, targets=("en",), translator=finto
    ) == 0
    riepilogo = riepilogo_esiti()
    assert riepilogo["conteggi"] == {"coppia non disponibile": 1}
    assert riepilogo["coppie_ferme"] == {"it→en": "coppia non disponibile"}
    LAST_ESITI.clear()


async def test_si_traduce_cio_che_il_lettore_vede(session: AsyncSession) -> None:
    """Il job traduce NELL'ORDINE della prima pagina: prima la story più
    pesata della finestra di attualità; quelle fuori finestra non rubano
    lavoro. (Prima le due liste divergevano: pagina piena di titoli mai
    tradotti mentre il job lavorava su story che nessuno guardava.)"""
    from datetime import datetime, timedelta

    from core.nlp.translate import stories_to_translate

    adesso = datetime.now(UTC)
    in_apertura = Story(
        title_neutral="Story di apertura, grande e fresca",
        first_seen=adesso, last_seen=adesso - timedelta(hours=1),
        article_count=40, source_count=20,
    )
    minore = Story(
        title_neutral="Story minore ma attuale",
        first_seen=adesso, last_seen=adesso - timedelta(hours=2),
        article_count=4, source_count=3,
    )
    fuori = Story(
        title_neutral="Story gigantesca ma fuori finestra",
        first_seen=adesso, last_seen=adesso - timedelta(hours=90),
        article_count=200, source_count=50,
    )
    session.add_all([in_apertura, minore, fuori])
    await session.flush()

    ordinate = await stories_to_translate(session, limit=10)
    titoli = [s.title_neutral for s in ordinate]
    assert titoli[0] == "Story di apertura, grande e fresca"
    assert "Story minore ma attuale" in titoli
    assert "Story gigantesca ma fuori finestra" not in titoli


async def test_traduzione_mirata_delle_story_visibili(
    session: AsyncSession,
) -> None:
    """translate_missing: solo le story chieste, solo nella lingua chiesta."""
    from core.nlp.translate import translate_missing

    story = await _story_italiana(session)
    finto = TraduttoreRegistratore({("it", "en"): "[EN] visibile subito"})
    fatte = await translate_missing(session, [story.id, 99999], "en", translator=finto)
    assert fatte == 1
    assert story.title_translations["en"] == "[EN] visibile subito"
    # Una sola chiamata: la lingua era una, la story inesistente si ignora.
    assert len(finto.chiamate) == 1


async def test_kick_traduzioni_dalla_prima_pagina(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Il fuoco-e-dimentica della prima pagina traduce davvero in
    background e non accoda mai due volte la stessa story."""
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from core import db
    from core.nlp.translate import kick_translations, set_translator

    story = await _story_italiana(session)
    await session.commit()

    finto = TraduttoreRegistratore({("it", "en"): "[EN] dal kick"})
    set_translator(finto)
    maker = async_sessionmaker(session.bind, expire_on_commit=False)
    monkeypatch.setattr(db, "get_sessionmaker", lambda: maker)

    task = kick_translations([story.id], "en")
    assert task is not None
    # Ri-chiedere subito la stessa story non accoda un secondo lavoro.
    assert kick_translations([story.id], "en") is None
    await asyncio.wait_for(task, timeout=10)

    await session.refresh(story)
    assert story.title_translations["en"] == "[EN] dal kick"
    # A lavoro finito si può richiedere di nuovo (ma non serve più).
    set_translator(None)
    assert kick_translations([story.id], "en") is None  # traduttore assente


async def test_traduzione_salvata_aggiorna_il_segnale_per_il_client(
    session: AsyncSession,
) -> None:
    """Quando una traduzione viene salvata (anche dal kick in background),
    il client deve potersene accorgere: LAST_TRANSLATION_AT avanza e la
    pastiglia «nuove notizie» compare."""
    from core.nlp import translate as modulo

    modulo.LAST_TRANSLATION_AT = None
    story = await _story_italiana(session)
    finto = TraduttoreRegistratore({("it", "en"): "[EN] segnale"})
    assert await translate_story_title(
        session, story, targets=("en",), translator=finto
    ) == 1
    assert modulo.LAST_TRANSLATION_AT is not None
    modulo.LAST_TRANSLATION_AT = None

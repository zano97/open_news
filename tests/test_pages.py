"""Fase 5: prima pagina broadsheet, pagina story, edizione lampo, entità."""

import html
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import Article, Coverage, Owner, Ownership, Source, Story
from core.nlp.entities import extract_entities

ORA = datetime.now(UTC) - timedelta(hours=2)  # sempre dentro le finestre

TITOLI = [
    "Vertice europeo sull'energia: intesa raggiunta a notte fonda",
    "Energia, i leader europei trovano l'accordo dopo una notte di trattative",
    "Accordo al vertice europeo sull'energia: cosa prevede l'intesa",
    "Energia: fumata bianca al vertice europeo",
    "I leader europei firmano l'intesa sull'energia",
]


async def _mini_giornale(session: AsyncSession) -> Story:
    fonti = []
    for i, country in enumerate(["it", "it", "fr", "de", "gb"]):
        fonte = Source(
            slug=f"testata-{i}", name=f"Testata {i}", domain=f"t{i}.test",
            country=country, language="it" if country == "it" else "en",
            region="europe", feed_urls=[], terms_note="",
        )
        session.add(fonte)
        fonti.append(fonte)
    await session.flush()

    proprietario = Owner(name="Editrice di Prova S.p.A.", type="società")
    session.add(proprietario)
    await session.flush()
    session.add(
        Ownership(
            source_id=fonti[0].id, owner_id=proprietario.id,
            evidence_name="Wikidata", evidence_url=None,
        )
    )

    story = Story(
        title_neutral=TITOLI[0],
        first_seen=ORA,
        last_seen=ORA + timedelta(minutes=90),
        article_count=5,
        source_count=5,
        is_flash=True,
        topic="energia",
        entities=[{"label": "Consiglio Europeo", "qid": None, "type": None}],
    )
    session.add(story)
    await session.flush()
    for fonte, titolo in zip(fonti, TITOLI, strict=True):
        session.add(
            Article(
                source_id=fonte.id,
                url=f"https://{fonte.domain}/vertice",
                title=titolo,
                snippet="Un breve estratto dell'articolo per la prova.",
                published_at=ORA + timedelta(minutes=10 * fonte.id),
                language=fonte.language,
                story_id=story.id,
            )
        )
    session.add(
        Coverage(
            story_id=story.id,
            by_country={"it": 2, "fr": 1, "de": 1, "gb": 1},
            by_language={"it": 2, "en": 3},
            blindspot_for=[{"group": "us", "kind": "country", "threshold": 0.5}],
            method_version="0.1.0",
        )
    )
    await session.commit()
    return story


async def test_prima_pagina(client: AsyncClient, session: AsyncSession) -> None:
    await _mini_giornale(session)
    resp = await client.get("/")
    assert resp.status_code == 200
    testo = resp.text
    assert "story-apertura" in testo  # la story più coperta apre il giornale
    assert "Testata 0" in testo  # le versioni delle testate sono a confronto
    assert "angolo cieco: US" in testo
    assert "lampo" in testo


async def test_pagina_storia(client: AsyncClient, session: AsyncSession) -> None:
    story = await _mini_giornale(session)
    resp = await client.get(f"/storia/{story.id}")
    assert resp.status_code == 200
    testo = html.unescape(resp.text)
    # Tutte le versioni affiancate con testata e proprietario.
    for titolo in TITOLI:
        assert titolo in testo
    assert "Editrice di Prova" in testo
    assert "Chi l'ha pubblicata per prima" in testo
    assert "Angolo cieco" in testo
    assert "Consiglio Europeo" in testo
    assert "non collegata" in testo  # QID assente dichiarato, mai inventato
    assert "Da dove vengono questi dati?" in testo


async def test_storia_inesistente(client: AsyncClient) -> None:
    resp = await client.get("/storia/99999")
    assert resp.status_code == 404


async def test_edizione_lampo(client: AsyncClient, session: AsyncSession) -> None:
    await _mini_giornale(session)
    resp = await client.get("/lampo")
    assert resp.status_code == 200
    testo = resp.text
    assert "reel-scheda" in testo
    assert "Coperta da" in testo
    assert "5" in testo and "paesi" in testo
    assert "Leggi le fonti" in testo
    assert "Angolo cieco per: US" in testo
    # Tre versioni a confronto, con la proprietà in piccolo.
    assert testo.count("reel-versione-titolo") == 3
    assert "proprietà: Editrice di Prova S.p.A." in testo


async def test_lampo_vuoto(client: AsyncClient) -> None:
    resp = await client.get("/lampo")
    assert resp.status_code == 200
    assert "Nessuna notizia lampo" in resp.text


class TestEntities:
    def test_entita_ricorrenti(self) -> None:
        titoli = [
            "Il presidente Mario Draghi incontra i sindacati a Roma",
            "Sindacati, l'incontro con Mario Draghi finisce senza accordo",
        ]
        labels = {e["label"] for e in extract_entities(titoli)}
        assert "Mario Draghi" in labels

    def test_titolo_singolo(self) -> None:
        labels = {e["label"] for e in extract_entities(["Elezioni in Baviera, vince la Csu"])}
        assert "Baviera" in labels

    def test_inizio_frase_non_basta(self) -> None:
        # Parole capitalizzate solo perché a inizio frase non diventano entità.
        entities = extract_entities(["Domani si vota", "Domani sciopero dei treni"])
        assert all(e["label"] != "Domani" for e in entities)


async def test_banner_demo_solo_con_notizie_demo(
    client: AsyncClient, session: AsyncSession
) -> None:
    # Senza articoli demo: nessun banner.
    resp = await client.get("/")
    assert "banner-demo" not in resp.text

    # Con una testata demo e un suo articolo: il banner dichiara la demo.
    demo = Source(
        slug="demo-prova", name="Testata Demo (demo)", domain="demo-prova.invalid",
        country="it", language="it", region="world", feed_urls=[],
        terms_note="fonte dimostrativa",
    )
    session.add(demo)
    await session.flush()
    session.add(
        Article(source_id=demo.id, url="https://demo-prova.invalid/1", title="Notizia demo")
    )
    await session.commit()

    resp = await client.get("/")
    assert "banner-demo" in resp.text
    assert "notizie dimostrative" in resp.text


async def test_filtro_per_paese(client: AsyncClient, session: AsyncSession) -> None:
    """La prima pagina è mondiale di default; con ?paese=xx mostra solo le
    story coperte da almeno una testata di quel paese."""
    it_fonte = Source(
        slug="filtro-it", name="Gazzetta Filtro", domain="filtro-it.test",
        country="it", language="it", region="italy", feed_urls=[], terms_note="",
    )
    gb_fonte = Source(
        slug="filtro-gb", name="Filter Gazette", domain="filtro-gb.test",
        country="gb", language="en", region="europe", feed_urls=[], terms_note="",
    )
    session.add_all([it_fonte, gb_fonte])
    await session.flush()
    story_it = Story(title_neutral="Notizia solo italiana", source_count=1, article_count=1)
    story_gb = Story(title_neutral="British-only story", source_count=1, article_count=1)
    session.add_all([story_it, story_gb])
    await session.flush()
    session.add_all([
        Article(source_id=it_fonte.id, url="https://filtro-it.test/1",
                title="Notizia solo italiana", story_id=story_it.id),
        Article(source_id=gb_fonte.id, url="https://filtro-gb.test/1",
                title="British-only story", story_id=story_gb.id),
    ])
    await session.commit()

    # Default: tutto il mondo, entrambe le story e la barra dei paesi.
    tutto = await client.get("/")
    assert "Notizia solo italiana" in tutto.text
    assert "British-only story" in tutto.text
    assert "filtro-paesi" in tutto.text
    assert "Tutto il mondo" in tutto.text

    solo_gb = await client.get("/?paese=gb")
    assert "British-only story" in solo_gb.text
    assert "Notizia solo italiana" not in solo_gb.text
    assert "almeno una testata di: GB" in solo_gb.text

    # Paese sconosciuto: ignorato, si torna al mondo intero.
    invalido = await client.get("/?paese=zz")
    assert "Notizia solo italiana" in invalido.text
    assert "British-only story" in invalido.text


async def test_mappa_dei_paesi(client: AsyncClient, session: AsyncSession) -> None:
    """/paesi: la mappa del mondo con i paesi coperti colorati e cliccabili."""
    await _mini_giornale(session)
    resp = await client.get("/paesi")
    assert resp.status_code == 200
    testo = resp.text
    assert 'id="it"' in testo  # il tracciato dell'Italia c'è
    assert "dati-mappa" in testo  # i conteggi per il JS
    assert 'href="/?paese=it"' in testo  # e il chip di riserva senza JS
    assert "chip-nome" in testo


async def test_prima_pagina_privilegia_l_attualita(
    client: AsyncClient, session: AsyncSession
) -> None:
    """La prima pagina è il giornale di OGGI: una story enorme ma ferma da
    ieri decade sotto una story fresca; una fuori finestra sparisce."""
    adesso = datetime.now(UTC)
    fonte = Source(
        slug="attualita-src", name="Fonte Attualità", domain="att.test",
        country="it", language="it", region="italy", feed_urls=[], terms_note="",
    )
    session.add(fonte)
    await session.flush()
    vecchia_grossa = Story(
        title_neutral="Vecchia storia enorme ferma da un giorno e mezzo",
        first_seen=adesso - timedelta(hours=40),
        last_seen=adesso - timedelta(hours=36),
        article_count=60, source_count=30,
    )
    fresca = Story(
        title_neutral="Notizia fresca di stamattina con poche testate",
        first_seen=adesso - timedelta(days=10),  # nata giorni fa, viva oggi
        last_seen=adesso - timedelta(hours=1),
        article_count=8, source_count=5,
    )
    fuori_finestra = Story(
        title_neutral="Storia gigantesca ma di quattro giorni fa",
        first_seen=adesso - timedelta(hours=90),
        last_seen=adesso - timedelta(hours=80),
        article_count=99, source_count=40,
    )
    session.add_all([vecchia_grossa, fresca, fuori_finestra])
    await session.commit()

    resp = await client.get("/")
    testo = resp.text
    assert "Notizia fresca di stamattina" in testo
    assert "Vecchia storia enorme" in testo
    assert "Storia gigantesca" not in testo  # fuori dalla finestra di 48h
    # La fresca sta SOPRA la grossa ferma: copertura scontata del tempo.
    assert testo.index("Notizia fresca di stamattina") < testo.index(
        "Vecchia storia enorme"
    )

    # La data della scheda è l'ULTIMO aggiornamento, non la prima apparizione.
    from apps.api.templating import _MESI

    locale_oggi = (adesso - timedelta(hours=1)).astimezone()
    attesa = f"{locale_oggi.day} {_MESI['it'][locale_oggi.month - 1]} {locale_oggi.year}"
    nascita = (adesso - timedelta(days=10)).astimezone()
    vietata = f"{nascita.day} {_MESI['it'][nascita.month - 1]} {nascita.year}"
    assert attesa in testo
    assert vietata not in testo


async def test_prima_pagina_mai_vuota(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Archivio fermo (solo story vecchie): meglio le più recenti che una
    pagina bianca."""
    adesso = datetime.now(UTC)
    story = Story(
        title_neutral="Unica storia rimasta, vecchia di una settimana",
        first_seen=adesso - timedelta(days=7),
        last_seen=adesso - timedelta(days=7),
        article_count=3, source_count=2,
    )
    session.add(story)
    await session.commit()
    resp = await client.get("/")
    assert "Unica storia rimasta" in resp.text

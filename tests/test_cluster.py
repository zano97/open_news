"""Fase 2: embedding, KNN, clustering incrementale, copertura, flash."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core import provenance
from core.cluster.coverage import compute_coverage
from core.cluster.incremental import cluster_pending, refresh_title_neutral
from core.config import get_settings
from core.models import Article, Coverage, Source, Story
from core.nlp.embed import HashingEmbedder, cosine

ORA = datetime(2026, 8, 27, 10, 0, tzinfo=UTC)

# Titoli dello stesso evento raccontato da testate diverse.
TERREMOTO = [
    "Terremoto di magnitudo 5.4 colpisce il centro Italia, paura tra i residenti",
    "Terremoto nel centro Italia: scossa di magnitudo 5.4 avvertita dai residenti",
    "Paura per il terremoto di magnitudo 5.4 nel centro Italia, nessuna vittima",
    "Centro Italia, terremoto di magnitudo 5.4: scossa avvertita, paura tra i residenti",
    "Scossa di terremoto magnitudo 5.4 nel centro Italia: paura ma nessuna vittima",
]
ALTRO_EVENTO = "La nazionale vince la finale del torneo dopo i rigori davanti ai tifosi"


@pytest.fixture(autouse=True)
def soglia_test() -> None:
    """Soglia esplicita nei test di clustering, indipendente dalla calibrazione."""
    settings = get_settings()
    originale = settings.cluster_similarity_threshold
    settings.cluster_similarity_threshold = 0.4
    yield
    settings.cluster_similarity_threshold = originale


async def _fonte(session: AsyncSession, slug: str, country: str = "it") -> Source:
    fonte = Source(
        slug=slug, name=slug, domain=f"{slug}.test", country=country,
        language="it", region="italy", feed_urls=[], terms_note="",
    )
    session.add(fonte)
    await session.flush()
    return fonte


async def _articolo(
    session: AsyncSession, fonte: Source, titolo: str, *,
    quando: datetime = ORA, url_suffix: str = "", snippet: str = "",
) -> Article:
    articolo = Article(
        source_id=fonte.id,
        url=f"https://{fonte.domain}/{abs(hash(titolo + url_suffix))}",
        title=titolo,
        snippet=snippet,
        published_at=quando,
        language="it",
    )
    session.add(articolo)
    await session.flush()
    return articolo


class TestEmbedder:
    def test_deterministico_e_normalizzato(self) -> None:
        emb = HashingEmbedder(dim=768)
        v1 = emb.embed(TERREMOTO[0])
        v2 = emb.embed(TERREMOTO[0])
        assert v1 == v2
        assert len(v1) == 768
        assert abs(sum(x * x for x in v1) - 1.0) < 1e-9

    def test_simili_piu_vicini_dei_diversi(self) -> None:
        emb = HashingEmbedder(dim=768)
        stesso = cosine(emb.embed(TERREMOTO[0]), emb.embed(TERREMOTO[1]))
        diverso = cosine(emb.embed(TERREMOTO[0]), emb.embed(ALTRO_EVENTO))
        assert stesso > 0.5
        assert diverso < 0.3
        assert stesso > diverso


async def test_stesso_evento_una_story(session: AsyncSession) -> None:
    for i, titolo in enumerate(TERREMOTO[:3]):
        fonte = await _fonte(session, f"fonte{i}")
        await _articolo(session, fonte, titolo, quando=ORA + timedelta(minutes=10 * i))
    stats = await cluster_pending(session)
    assert stats.processed == 3
    assert stats.created == 1
    assert stats.attached == 2

    story = (await session.execute(select(Story))).scalar_one()
    assert story.article_count == 3
    assert story.source_count == 3
    assert story.title_neutral in TERREMOTO[:3]
    # Il titolo neutro è quello più vicino al centroide, mai generato.
    assert story.title_method == "centroide"

    prova = await provenance.for_entity(session, "story", story.id)
    campi = {p.field for p in prova}
    assert "cluster" in campi


async def test_eventi_diversi_story_diverse(session: AsyncSession) -> None:
    a = await _fonte(session, "fonte-a")
    b = await _fonte(session, "fonte-b")
    await _articolo(session, a, TERREMOTO[0])
    await _articolo(session, b, ALTRO_EVENTO)
    stats = await cluster_pending(session)
    assert stats.created == 2
    stories = list((await session.execute(select(Story))).scalars())
    assert len(stories) == 2


async def test_finestra_temporale_72h(session: AsyncSession) -> None:
    fonte = await _fonte(session, "fonte-vecchia")
    vecchio = await _articolo(
        session, fonte, TERREMOTO[0], quando=ORA - timedelta(hours=100)
    )
    await cluster_pending(session)
    assert vecchio.story_id is not None

    nuova_fonte = await _fonte(session, "fonte-nuova")
    await _articolo(session, nuova_fonte, TERREMOTO[1], quando=ORA)
    stats = await cluster_pending(session)
    # Stesso testo ma fuori finestra: nasce una story nuova.
    assert stats.created == 1
    stories = list((await session.execute(select(Story))).scalars())
    assert len(stories) == 2


async def test_story_lampo(session: AsyncSession) -> None:
    for i, titolo in enumerate(TERREMOTO):
        fonte = await _fonte(session, f"lampo{i}")
        await _articolo(session, fonte, titolo, quando=ORA + timedelta(minutes=15 * i))
    stats = await cluster_pending(session)
    story = (await session.execute(select(Story))).scalar_one()
    assert story.source_count == 5
    assert story.is_flash  # 5 testate in poco più di un'ora
    assert stats.new_flash == [story.id]


async def test_non_lampo_se_lento(session: AsyncSession) -> None:
    for i, titolo in enumerate(TERREMOTO):
        fonte = await _fonte(session, f"lento{i}")
        # Una fonte ogni 10 ore: mai 5 fonti entro 2 ore.
        await _articolo(session, fonte, titolo, quando=ORA + timedelta(hours=10 * i))
    await cluster_pending(session)
    story = (await session.execute(select(Story))).scalar_one()
    assert story.source_count == 5
    assert not story.is_flash


async def test_idempotente(session: AsyncSession) -> None:
    fonte = await _fonte(session, "fonte-idem")
    await _articolo(session, fonte, TERREMOTO[0])
    prima = await cluster_pending(session)
    seconda = await cluster_pending(session)
    assert prima.processed == 1
    assert seconda.processed == 0


async def test_coverage_per_paese_e_lingua(session: AsyncSession) -> None:
    it = await _fonte(session, "cov-it", country="it")
    fr = await _fonte(session, "cov-fr", country="fr")
    await _articolo(session, it, TERREMOTO[0])
    await _articolo(session, fr, TERREMOTO[1])
    await cluster_pending(session)
    story = (await session.execute(select(Story))).scalar_one()
    coverage = await compute_coverage(session, story)
    assert coverage.by_country == {"it": 1, "fr": 1}
    assert coverage.by_language == {"it": 2}
    assert coverage.method_version

    riga = (await session.execute(select(Coverage))).scalar_one()
    assert riga.story_id == story.id


async def test_titolo_neutro_vicino_al_centroide(session: AsyncSession) -> None:
    fonti = [await _fonte(session, f"tn{i}") for i in range(3)]
    for fonte, titolo in zip(fonti, TERREMOTO[:3], strict=True):
        await _articolo(session, fonte, titolo)
    await cluster_pending(session)
    story = (await session.execute(select(Story))).scalar_one()
    prima_scelta = story.title_neutral
    await refresh_title_neutral(session, story)
    assert story.title_neutral == prima_scelta  # deterministico

async def test_titolo_neutro_preferisce_articoli_dal_feed(
    session: AsyncSession,
) -> None:
    """I titoli GDELT (senza snippet) sono ritokenizzati alla fonte: quando
    il cluster ha anche UN titolo editoriale intatto (dal feed, con snippet),
    è quello a diventare il titolo neutro, anche se non è il più centrale."""
    for i, titolo in enumerate(TERREMOTO[:3]):
        fonte = await _fonte(session, f"tf{i}")
        await _articolo(session, fonte, titolo)  # snippet vuoto: stile GDELT
    dal_feed = await _fonte(session, "tf-feed")
    await _articolo(
        session, dal_feed, TERREMOTO[3],
        snippet="Scossa di magnitudo 5.4 avvertita nel centro Italia.",
    )
    await cluster_pending(session)
    story = (await session.execute(select(Story))).scalar_one()
    assert story.title_neutral == TERREMOTO[3]

    # Senza titoli editoriali il più vicino al centroide resta la scelta.
    await refresh_title_neutral(session, story)
    assert story.title_neutral == TERREMOTO[3]  # stabile anche al refresh

async def test_articolo_indigesto_non_blocca_la_coda(
    session: AsyncSession,
) -> None:
    """La coda è ordinata per data: un articolo che solleva un'eccezione in
    testa NON deve congelare per sempre l'arrivo delle notizie nuove."""
    class EmbedderVelenoso(HashingEmbedder):
        def embed(self, text: str) -> list[float]:
            if "veleno" in text:
                raise RuntimeError("boom")
            return super().embed(text)

    fonte = await _fonte(session, "veleno-src")
    await _articolo(
        session, fonte, "Un articolo veleno che rompe l'embedding",
        quando=ORA - timedelta(hours=1),
    )
    buona = await _fonte(session, "buona-src")
    await _articolo(session, buona, TERREMOTO[0], quando=ORA)

    stats = await cluster_pending(session, embedder=EmbedderVelenoso(dim=768))
    assert stats.skipped == 1
    assert stats.processed == 1  # la notizia buona è passata comunque
    story = (await session.execute(select(Story))).scalar_one()
    assert story.title_neutral == TERREMOTO[0]

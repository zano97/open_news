"""Fase 6: alpha di Krippendorff, regole di pubblicazione, flusso di annotazione."""

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import hash_password, verify_password
from core.bias.annotation import (
    aggregate_source_annotation,
    compute_annotation_signals,
    krippendorff_alpha_ordinal,
    orientation_bucket,
)
from core.models import Annotation, AnnotatorProfile, Article, BiasSignal, Source


class TestAlpha:
    def test_accordo_perfetto(self) -> None:
        ratings = {u: {1: 1, 2: 1, 3: 1} for u in range(10)}
        assert krippendorff_alpha_ordinal(ratings) == 1.0

    def test_disaccordo_sistematico(self) -> None:
        # Metà giudizi agli estremi opposti su ogni unità: accordo pessimo.
        ratings = {u: {1: -2, 2: 2} for u in range(20)}
        alpha = krippendorff_alpha_ordinal(ratings)
        assert alpha is not None
        assert alpha < 0.2

    def test_accordo_alto_ma_non_perfetto(self) -> None:
        ratings: dict[int, dict[int, int]] = {}
        for u in range(30):
            base = -1 if u % 3 == 0 else 1
            ratings[u] = {1: base, 2: base, 3: base}
        ratings[0][3] = 0  # un solo scarto di un punto
        alpha = krippendorff_alpha_ordinal(ratings)
        assert alpha is not None
        assert 0.8 < alpha < 1.0

    def test_dati_insufficienti(self) -> None:
        assert krippendorff_alpha_ordinal({1: {1: 2}}) is None
        assert krippendorff_alpha_ordinal({}) is None

    def test_fasce_orientamento(self) -> None:
        assert orientation_bucket(-2) == "meno"
        assert orientation_bucket(0) == "centro"
        assert orientation_bucket(1.5) == "piu"


async def _setup_annotations(
    session: AsyncSession,
    *,
    n_articles: int,
    annotators: list[tuple[float, float]],
    agreeing: bool = True,
) -> Source:
    fonte = Source(
        slug="annotata", name="Fonte Annotata", domain="annotata.test",
        country="it", language="it", region="italy", feed_urls=[], terms_note="",
    )
    session.add(fonte)
    await session.flush()
    profiles = []
    for i, (eco, cul) in enumerate(annotators):
        profile = AnnotatorProfile(
            username=f"annotatore{i}",
            password_hash=hash_password("password-sicura"),
            self_axis_economic=eco,
            self_axis_cultural=cul,
        )
        session.add(profile)
        profiles.append(profile)
    await session.flush()
    for j in range(n_articles):
        article = Article(
            source_id=fonte.id, url=f"https://annotata.test/{j}", title=f"Articolo {j}"
        )
        session.add(article)
        await session.flush()
        for k, profile in enumerate(profiles):
            value = 1 if agreeing else (2 if k % 2 == 0 else -2)
            for axis in ("economic", "cultural"):
                session.add(
                    Annotation(
                        article_id=article.id,
                        annotator_id=profile.id,
                        axis=axis,
                        value=value,
                    )
                )
    await session.flush()
    return fonte


async def test_etichetta_pubblicata_con_protocollo(session: AsyncSession) -> None:
    fonte = await _setup_annotations(
        session,
        n_articles=55,
        annotators=[(-2, -1), (0, 0), (2, 1)],  # tre fasce diverse
        agreeing=True,
    )
    result = await aggregate_source_annotation(session, fonte, "economic")
    assert result["status"] == "pubblicata"
    assert result["label"] == 1.0
    assert result["alpha"] == 1.0
    assert result["n_articles"] == 55
    assert len(result["buckets"]) == 3


async def test_in_valutazione_pochi_articoli(session: AsyncSession) -> None:
    fonte = await _setup_annotations(
        session, n_articles=10, annotators=[(-2, 0), (0, 0), (2, 0)]
    )
    result = await aggregate_source_annotation(session, fonte, "economic")
    assert result["status"] == "in valutazione"
    assert any("articoli annotati 10/50" in m for m in result["missing"])


async def test_in_valutazione_stessa_fascia(session: AsyncSession) -> None:
    # Tre annotatori, ma tutti dichiarano lo stesso orientamento.
    fonte = await _setup_annotations(
        session, n_articles=55, annotators=[(2, 2), (1, 1), (2, 1)]
    )
    result = await aggregate_source_annotation(session, fonte, "economic")
    assert result["status"] == "in valutazione"
    assert any("seconda fascia" in m for m in result["missing"])


async def test_in_valutazione_accordo_basso(session: AsyncSession) -> None:
    fonte = await _setup_annotations(
        session, n_articles=55, annotators=[(-2, 0), (0, 0), (2, 0)], agreeing=False
    )
    result = await aggregate_source_annotation(session, fonte, "economic")
    assert result["status"] == "in valutazione"
    assert any("α" in m for m in result["missing"])


async def test_segnali_annotation_scritti(session: AsyncSession) -> None:
    await _setup_annotations(session, n_articles=5, annotators=[(0, 0)])
    written = await compute_annotation_signals(session)
    assert written == 2  # due assi
    signals = list(
        (
            await session.execute(
                select(BiasSignal).where(BiasSignal.signal_type == "annotation")
            )
        ).scalars()
    )
    assert {s.axis for s in signals} == {"economic", "cultural"}


class TestPassword:
    def test_hash_e_verifica(self) -> None:
        stored = hash_password("segretissima")
        assert verify_password("segretissima", stored)
        assert not verify_password("sbagliata", stored)
        assert not verify_password("segretissima", "malformata")


async def test_flusso_completo_annotazione(
    client: AsyncClient, session: AsyncSession
) -> None:
    fonte = Source(
        slug="da-annotare", name="Da Annotare", domain="da.test", country="it",
        language="it", region="italy", feed_urls=[], terms_note="", enabled=True,
    )
    session.add(fonte)
    await session.flush()
    article = Article(
        source_id=fonte.id,
        url="https://da.test/1",
        title="Titolo da valutare alla cieca",
        snippet="Snippet di prova.",
    )
    session.add(article)
    await session.commit()

    # Registrazione con orientamento dichiarato.
    resp = await client.post(
        "/annota/registrati",
        data={
            "username": "mario", "password": "password-sicura",
            "self_axis_economic": "-1", "self_axis_cultural": "1",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "opennews_sessione" in resp.cookies

    client.cookies.update(resp.cookies)
    scheda = await client.get("/annota")
    assert scheda.status_code == 200
    testo = scheda.text
    assert "Titolo da valutare alla cieca" in testo
    # Cecità: la testata non compare da nessuna parte nella scheda.
    assert "Da Annotare" not in testo
    assert "da.test" not in testo

    salva = await client.post(
        "/annota",
        data={
            "article_id": str(article.id), "economic": "-1",
            "cultural": "na", "confidence": "3",
        },
        follow_redirects=False,
    )
    assert salva.status_code == 303
    annotations = list((await session.execute(select(Annotation))).scalars())
    assert len(annotations) == 2
    economic = next(a for a in annotations if a.axis == "economic")
    assert economic.value == -1
    cultural = next(a for a in annotations if a.axis == "cultural")
    assert cultural.value is None
    assert cultural.not_applicable

    # L'articolo annotato non viene riproposto.
    dopo = await client.get("/annota")
    assert "Titolo da valutare alla cieca" not in dopo.text


async def test_export_annotazioni_anonimo(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _setup_annotations(session, n_articles=2, annotators=[(1, 1)])
    await session.commit()
    resp = await client.get("/dati/annotazioni.csv")
    assert resp.status_code == 200
    testo = resp.text
    assert "CC BY-SA 4.0" in testo
    assert "annotatore0" not in testo  # mai il nome utente
    assert ",a1," in testo or ",a" in testo


async def test_login_sbagliato(client: AsyncClient) -> None:
    resp = await client.post(
        "/annota/entra", data={"username": "nessuno", "password": "x" * 10}
    )
    assert resp.status_code == 401

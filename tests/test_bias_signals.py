"""Fase 4: segnali di livello 2 e 3 su un mini-corpus (integrazione)."""

from datetime import UTC, datetime

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core import provenance
from core.bias.aggregate import compute_weekly_signals
from core.bias.selection import (
    assign_story_topics,
    cocoverage_map,
    compute_agenda,
    compute_blindspots,
)
from core.config import DATA_DIR
from core.models import Article, BiasSignal, Coverage, Source, Story, utcnow

ORA = datetime(2026, 8, 27, 9, 0, tzinfo=UTC)


def _keyword(topic_id: str, lang: str = "it") -> str:
    raw = yaml.safe_load((DATA_DIR / "topics.yaml").read_text())
    return str(
        next(t["keywords"][lang] for t in raw["topics"] if t["id"] == topic_id)[0]
    )


async def _fonte(
    session: AsyncSession, slug: str, country: str = "it"
) -> Source:
    fonte = Source(
        slug=slug, name=slug.title(), domain=f"{slug}.test", country=country,
        language="it", region="italy", feed_urls=[], terms_note="",
    )
    session.add(fonte)
    await session.flush()
    return fonte


async def _story_con_articoli(
    session: AsyncSession,
    titolo: str,
    fonti: list[Source],
    *,
    topic: str | None = None,
    first_seen: datetime | None = None,
) -> Story:
    story = Story(
        title_neutral=titolo, first_seen=first_seen or utcnow(),
        last_seen=utcnow(), topic=topic,
        article_count=len(fonti), source_count=len(fonti),
    )
    session.add(story)
    await session.flush()
    for fonte in fonti:
        session.add(
            Article(
                source_id=fonte.id,
                url=f"https://{fonte.domain}/{abs(hash(titolo))}-{fonte.id}",
                title=titolo,
                snippet="",
                language="it",
                story_id=story.id,
            )
        )
    await session.flush()
    return story


async def test_assegnazione_temi_alle_story(session: AsyncSession) -> None:
    fonte = await _fonte(session, "temi")
    kw = _keyword("immigrazione")
    story = await _story_con_articoli(session, f"Nuovi dati sugli {kw} nel 2026", [fonte])
    n = await assign_story_topics(session, since=ORA)
    assert n >= 1
    await session.refresh(story)
    assert story.topic == "immigrazione"
    prova = await provenance.for_entity(session, "story", story.id)
    assert any(p.field == "topic" for p in prova)


async def test_agenda_con_bootstrap(session: AsyncSession) -> None:
    a = await _fonte(session, "agenda-a")
    b = await _fonte(session, "agenda-b")
    # A copre quasi solo immigrazione, B quasi solo sport.
    for i in range(12):
        await _story_con_articoli(session, f"story imm {i}", [a], topic="immigrazione")
        await _story_con_articoli(session, f"story sport {i}", [b], topic="sport")
    for i in range(3):
        await _story_con_articoli(session, f"comune {i}", [a, b], topic="economia_finanza")

    scritti = await compute_agenda(session, window_days=30)
    assert scritti == 2

    segnale_a = (
        await session.execute(
            select(BiasSignal).where(
                BiasSignal.source_id == a.id, BiasSignal.signal_type == "agenda"
            )
        )
    ).scalar_one()
    valore = segnale_a.value
    assert valore["immigrazione"]["deviation"] > 0
    assert valore["sport"]["deviation"] < 0
    assert valore["immigrazione"]["ci_low"] <= valore["immigrazione"]["ci_high"]
    assert segnale_a.n_articles == 15
    # Idempotenza: il ricalcolo sostituisce, non accumula.
    await compute_agenda(session, window_days=30)
    segnali = list(
        (
            await session.execute(
                select(BiasSignal).where(BiasSignal.signal_type == "agenda")
            )
        ).scalars()
    )
    assert len(segnali) == 2


async def test_mappa_cocopertura(session: AsyncSession) -> None:
    a = await _fonte(session, "map-a")
    b = await _fonte(session, "map-b")
    c = await _fonte(session, "map-c")
    d = await _fonte(session, "map-d")
    # A e B coprono le stesse story; C e D un insieme diverso.
    for i in range(6):
        await _story_con_articoli(session, f"condivisa ab {i}", [a, b])
    for i in range(6):
        await _story_con_articoli(session, f"condivisa cd {i}", [c, d])
    for i in range(2):
        await _story_con_articoli(session, f"ponte {i}", [a, c])

    result = await cocoverage_map(session, window_days=30)
    assert result.n_sources >= 3
    assert set(result.positions) >= {"map-a", "map-b", "map-c"}
    assert result.axis_stories.get("x_positive") or result.axis_stories.get("x_negative")
    # A e B devono essere più vicine tra loro che a C.
    import math

    def dist(p: str, q: str) -> float:
        (x1, y1), (x2, y2) = result.positions[p], result.positions[q]
        return math.hypot(x1 - x2, y1 - y2)

    assert dist("map-a", "map-b") < dist("map-a", "map-c")


async def test_blind_spot(session: AsyncSession) -> None:
    a = await _fonte(session, "bs-a")
    b = await _fonte(session, "bs-b")
    c = await _fonte(session, "bs-c")
    # Story coperta da A e B ma non da C -> angolo cieco di C.
    ignorata = await _story_con_articoli(session, "grande notizia ignorata", [a, b])
    # C è attiva nel periodo (ha una sua story).
    await _story_con_articoli(session, "notizia di c", [c])

    scritti = await compute_blindspots(session, window_days=30)
    assert scritti == 3
    segnale_c = (
        await session.execute(
            select(BiasSignal).where(
                BiasSignal.source_id == c.id, BiasSignal.signal_type == "blindspot"
            )
        )
    ).scalar_one()
    assert segnale_c.value["count"] == 1
    assert ignorata.id in segnale_c.value["story_ids"]


async def test_blindspot_di_paese_v2_significativo(session: AsyncSession) -> None:
    """v2: si marca solo l'assenza IMPROBABILE. L'Italia (6 testate che
    coprono quasi tutte le grandi story) che ignora una story internazionale
    matura è un angolo cieco; il Portogallo (3 testate che coprono poco)
    no — la sua assenza è attesa, non significativa."""
    from datetime import timedelta

    it = [await _fonte(session, f"it-{i}", country="it") for i in range(6)]
    pt = [await _fonte(session, f"pt-{i}", country="pt") for i in range(3)]
    gb = [await _fonte(session, f"gb-{i}", country="gb") for i in range(3)]
    fr = [await _fonte(session, f"fr-{i}", country="fr") for i in range(2)]
    de = [await _fonte(session, f"de-{i}", country="de") for i in range(2)]

    # Storico: 12 grandi story; le italiane le coprono (propensione alta),
    # le portoghesi quasi mai (propensione bassa).
    for i in range(12):
        extra = [pt[0]] if i == 0 else []
        await _story_con_articoli(
            session, f"grande story {i}", it + gb[:1] + extra,
            first_seen=utcnow() - timedelta(hours=30),
        )

    # La story in esame: matura, 3 paesi, 7 testate — e zero italiane.
    ignorata = await _story_con_articoli(
        session, "vertice internazionale ignorato", gb + fr + de,
        first_seen=utcnow() - timedelta(hours=12),
    )
    session.add(Coverage(story_id=ignorata.id, method_version="test"))
    # Una story FRESCA con le stesse assenze non va marcata: c'è ancora tempo.
    fresca = await _story_con_articoli(
        session, "vertice appena battuto", gb + fr + de,
        first_seen=utcnow() - timedelta(hours=1),
    )
    session.add(Coverage(story_id=fresca.id, method_version="test"))
    await session.flush()

    await compute_blindspots(session, window_days=30)

    coverage = (
        await session.execute(select(Coverage).where(Coverage.story_id == ignorata.id))
    ).scalar_one()
    gruppi = {b["group"] for b in coverage.blindspot_for}
    assert "it" in gruppi  # assenza altamente improbabile: marcata
    assert "pt" not in gruppi  # assenza attesa (propensione bassa): niente rumore
    marcato = next(b for b in coverage.blindspot_for if b["group"] == "it")
    assert marcato["p_null"] < 0.05  # la soglia è dichiarata nel dato stesso

    fresca_cov = (
        await session.execute(select(Coverage).where(Coverage.story_id == fresca.id))
    ).scalar_one()
    assert fresca_cov.blindspot_for == []  # troppo presto per giudicare


async def test_pipeline_settimanale_completa(session: AsyncSession) -> None:
    a = await _fonte(session, "week-a")
    b = await _fonte(session, "week-b")
    kw = _keyword("economia_finanza")
    for i in range(12):
        await _story_con_articoli(session, f"Notizia su {kw} n.{i}", [a, b])
    summary = await compute_weekly_signals(session, window_days=30)
    assert summary["story_topics"] >= 12
    assert summary["agenda"] == 2
    assert summary["framing"] == 2
    assert summary["actors"] == 2
    assert summary["tone"] == 2

"""Fase 0: roundtrip dei modelli su SQLite con i tipi portabili."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core import provenance
from core.config import get_settings
from core.models import Article, Provenance, Source, Story


def _fonte(slug: str = "esempio") -> Source:
    return Source(
        slug=slug,
        name="Quotidiano d'Esempio",
        domain="esempio.it",
        country="it",
        language="it",
        region="italy",
        feed_urls=["https://esempio.it/rss"],
        terms_note="nessuna restrizione nota",
    )


async def test_source_article_roundtrip(session: AsyncSession) -> None:
    fonte = _fonte()
    session.add(fonte)
    await session.flush()

    dim = get_settings().embedding_dim
    articolo = Article(
        source_id=fonte.id,
        url="https://esempio.it/articolo-1",
        title="Un titolo d'esempio",
        snippet="Uno snippet breve.",
        published_at=datetime(2026, 8, 27, 10, 30, tzinfo=UTC),
        language="it",
        embedding=[0.1] * dim,
        embedding_method="hashing-ngram-v1",
        simhash="00ff00ff00ff00ff",
    )
    session.add(articolo)
    await session.commit()

    letto = (await session.execute(select(Article))).scalar_one()
    assert letto.embedding is not None
    assert len(letto.embedding) == dim
    assert letto.embedding[0] == pytest.approx(0.1)
    # I datetime tornano sempre timezone-aware UTC, anche da SQLite.
    assert letto.published_at is not None
    assert letto.published_at.tzinfo is not None
    assert letto.published_at.hour == 10


async def test_url_articolo_unico(session: AsyncSession) -> None:
    fonte = _fonte("doppione")
    session.add(fonte)
    await session.flush()
    session.add(Article(source_id=fonte.id, url="https://x.it/a", title="a"))
    await session.commit()
    session.add(Article(source_id=fonte.id, url="https://x.it/a", title="b"))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_datetime_naive_rifiutato(session: AsyncSession) -> None:
    fonte = _fonte("naive")
    session.add(fonte)
    await session.flush()
    session.add(
        Article(
            source_id=fonte.id,
            url="https://x.it/naive",
            title="t",
            published_at=datetime(2026, 1, 1),  # naive: deve essere rifiutato
        )
    )
    with pytest.raises(Exception, match="timezone-aware"):
        await session.commit()


async def test_provenance_idempotente(session: AsyncSession) -> None:
    story = Story(title_neutral="Evento di prova")
    session.add(story)
    await session.flush()

    await provenance.record(
        session,
        entity_type="story",
        entity_id=story.id,
        field="topic",
        method="keyword-taxonomy",
        inputs={"topics_file": "data/topics.yaml"},
    )
    await provenance.record(
        session,
        entity_type="story",
        entity_id=story.id,
        field="topic",
        method="keyword-taxonomy",
        inputs={"topics_file": "data/topics.yaml", "run": 2},
    )
    await session.commit()

    righe = await provenance.for_entity(session, "story", story.id)
    assert len(righe) == 1  # il ricalcolo sostituisce, non accumula
    assert righe[0].inputs["run"] == 2
    assert isinstance(righe[0], Provenance)
    assert righe[0].method_version

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

    # Interfaccia inglese: titolo tradotto + marcatura + originale dichiarato.
    pagina = await client.get(f"/storia/{story.id}?lang=en")
    assert "Government approves pension reform" in pagina.text
    assert "automatic translation" in pagina.text
    assert "Original headline" in pagina.text

    prima = await client.get("/?lang=en")
    assert "Government approves pension reform" in prima.text
    assert "transl." in prima.text

    # Interfaccia italiana: originale, nessuna marcatura.
    it_pagina = await client.get(f"/storia/{story.id}")
    assert "Il governo approva la riforma delle pensioni" in it_pagina.text
    assert "traduzione automatica" not in it_pagina.text

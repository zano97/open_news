"""Fase 7: `make seed --offline-demo` produce un giornale popolato, senza rete."""

import pytest
from sqlalchemy import func, select

from core.config import get_settings
from core.db import get_sessionmaker, reset_engine
from core.models import BiasSignal, Source, Story


@pytest.fixture
def db_su_file(tmp_path, monkeypatch) -> None:
    """Il seed usa engine/sessionmaker globali: puntali a un SQLite temporaneo."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/seed.sqlite3")
    get_settings.cache_clear()
    reset_engine()
    yield
    get_settings.cache_clear()
    reset_engine()


async def test_seed_offline_demo_completo(db_su_file: None) -> None:
    from scripts.seed import ensure_schema, seed_offline_demo

    await ensure_schema()
    await seed_offline_demo()

    maker = get_sessionmaker()
    async with maker() as session:
        n_sources = (
            await session.execute(select(func.count()).select_from(Source))
        ).scalar_one()
        assert n_sources >= 47 + 8  # catalogo reale + testate demo

        stories = list((await session.execute(select(Story))).scalars())
        assert len(stories) >= 8, "gli eventi demo devono raggrupparsi in story"
        multi = [s for s in stories if s.source_count >= 3]
        assert multi, "almeno una story coperta da più testate"
        assert any(s.is_flash for s in stories), "almeno una story lampo per /lampo"
        # Story raggruppate tra lingue diverse (via nomi/lessico condiviso o meno):
        # il requisito minimo è che il clustering abbia unito titoli parafrasati.
        assert any(s.article_count > s.source_count - 1 for s in multi)

        segnali = list((await session.execute(select(BiasSignal))).scalars())
        tipi = {s.signal_type for s in segnali}
        assert "tone" in tipi
        assert "framing" in tipi

        # Le testate demo sono dichiarate come tali, mai spacciate per reali.
        demo = (
            await session.execute(select(Source).where(Source.slug.like("demo-%")))
        ).scalars()
        for fonte in demo:
            assert "dimostrativa" in fonte.terms_note

    # Idempotenza: un secondo seed non duplica gli articoli.
    await seed_offline_demo()
    async with maker() as session:
        n_stories_dopo = (
            await session.execute(select(func.count()).select_from(Story))
        ).scalar_one()
    assert n_stories_dopo == len(stories)

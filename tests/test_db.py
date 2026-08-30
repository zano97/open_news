"""SQLite pronto per la concorrenza: WAL, busy_timeout, scritture parallele."""

import asyncio

import pytest
from sqlalchemy import text

from core import db as core_db


@pytest.fixture
def _engine_su_file(tmp_path, monkeypatch):
    """Un engine vero su file (l'in-memory non esercita WAL)."""
    url = f"sqlite+aiosqlite:///{tmp_path}/prova.sqlite3"
    monkeypatch.setenv("DATABASE_URL", url)
    # get_settings è cachato: senza svuotare la cache l'engine userebbe
    # ancora l'URL precedente (o quello di default).
    from core.config import get_settings

    get_settings.cache_clear()
    core_db.reset_engine()
    yield core_db.get_engine()
    core_db.reset_engine()
    get_settings.cache_clear()


async def test_pragmi_sqlite_attivi(_engine_su_file) -> None:
    """WAL e busy_timeout DEVONO essere attivi: con i default di fabbrica
    le scritture concorrenti dei job esplodevano in «database is locked»
    e il lavoro di interi giri andava perso al commit."""
    engine = _engine_su_file
    async with engine.connect() as conn:
        journal = (await conn.execute(text("PRAGMA journal_mode"))).scalar_one()
        timeout = (await conn.execute(text("PRAGMA busy_timeout"))).scalar_one()
    assert str(journal).lower() == "wal"
    assert int(timeout) >= 15000


async def test_scritture_concorrenti_senza_lock(_engine_su_file) -> None:
    """Due scrittori in parallelo sullo stesso file: con WAL + busy_timeout
    nessuno dei due deve fallire."""
    engine = _engine_su_file
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE prova (k INTEGER)"))

    async def scrittore(n: int) -> None:
        for i in range(25):
            async with engine.begin() as conn:
                await conn.execute(text("INSERT INTO prova (k) VALUES (:k)"), {"k": n * 100 + i})
            await asyncio.sleep(0)

    await asyncio.gather(scrittore(1), scrittore(2))
    async with engine.connect() as conn:
        totale = (await conn.execute(text("SELECT COUNT(*) FROM prova"))).scalar_one()
    assert totale == 50

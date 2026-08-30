"""Motore e sessioni SQLAlchemy async.

PostgreSQL 16 + pgvector in produzione; SQLite (aiosqlite) nei test.
Le differenze di tipo (vector, JSONB, datetime tz-aware) sono assorbite dai
tipi portabili definiti in `core.models.types`.
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _configura_sqlite(engine: AsyncEngine) -> None:
    """SQLite pronto per la concorrenza REALE dell'app personale.

    Raccolta, clustering, traduzioni, testi integrali e pagine web scrivono
    tutti sullo stesso file: con le impostazioni di fabbrica (journal
    rollback, nessuna attesa) le scritture concorrenti esplodono in
    «database is locked» e il lavoro di interi giri va perso al commit.
    - WAL: i lettori non bloccano lo scrittore e viceversa;
    - busy_timeout: chi trova il database occupato ASPETTA (fino a 15 s)
      invece di fallire;
    - synchronous=NORMAL: il compromesso documentato per WAL (mai corrotto,
      al peggio l'ultimissima transazione da rifare).
    """
    if not engine.url.get_backend_name().startswith("sqlite"):
        return
    from sqlalchemy import event

    @event.listens_for(engine.sync_engine, "connect")
    def _pragmas(dbapi_conn: object, _record: object) -> None:
        cursor = dbapi_conn.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=15000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        _configura_sqlite(_engine)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """Dependency FastAPI: una sessione per richiesta."""
    async with get_sessionmaker()() as session:
        yield session


def reset_engine() -> None:
    """Solo per i test: dimentica engine/sessionmaker globali."""
    global _engine, _sessionmaker
    _engine = None
    _sessionmaker = None

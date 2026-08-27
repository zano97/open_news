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


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(settings.database_url, pool_pre_ping=True)
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

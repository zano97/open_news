"""Fixture e2e: server uvicorn reale su SQLite popolato, browser Playwright."""

import asyncio
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest


@pytest.fixture(scope="session")
def browser_type_launch_args(
    browser_type_launch_args: dict[str, object],
) -> dict[str, object]:
    """Se PLAYWRIGHT_BROWSERS_PATH punta a un Chromium preinstallato di altra
    versione, usalo esplicitamente invece di pretendere il download."""
    executable = Path(
        os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/nonexistent"), "chromium"
    )
    if executable.exists():
        return {**browser_type_launch_args, "executable_path": str(executable)}
    return browser_type_launch_args


def _seed_database(db_path: Path) -> None:
    """Popola il DB e2e: catalogo fonti + una story lampo con 5 versioni."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from core.ingest.catalog import sync_catalog
    from core.models import Article, Base, Coverage, Source, Story

    async def seed() -> None:
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        ora = datetime.now(UTC)
        async with maker() as session:
            await sync_catalog(session)  # il catalogo popola /fonti e /fonte/{slug}
            prova = []
            for i, country in enumerate(["it", "fr", "de", "gb", "es"]):
                fonte = Source(
                    slug=f"e2e-{i}", name=f"Gazzetta E2E {i}", domain=f"e2e{i}.test",
                    country=country, language="it", region="europe",
                    feed_urls=[], terms_note="",
                )
                session.add(fonte)
                prova.append(fonte)
            await session.flush()
            story = Story(
                title_neutral="Vertice sul clima: raggiunta l'intesa tra i governi",
                first_seen=ora - timedelta(hours=1),
                last_seen=ora,
                article_count=5, source_count=5, is_flash=True, topic="clima_ambiente",
            )
            session.add(story)
            await session.flush()
            for i, fonte in enumerate(prova):
                session.add(
                    Article(
                        source_id=fonte.id,
                        url=f"https://{fonte.domain}/clima",
                        title=f"Clima, versione n.{i} del titolo sull'intesa",
                        snippet="Estratto breve di prova.",
                        published_at=ora - timedelta(minutes=50 - i),
                        language="it",
                        story_id=story.id,
                    )
                )
            session.add(
                Coverage(
                    story_id=story.id,
                    by_country={"it": 1, "fr": 1, "de": 1, "gb": 1, "es": 1},
                    by_language={"it": 5},
                    method_version="0.1.0",
                )
            )
            # Seconda story lampo: serve a provare la navigazione del reel.
            story2 = Story(
                title_neutral="Sciopero dei trasporti: adesione altissima in tutto il paese",
                first_seen=ora - timedelta(hours=2),
                last_seen=ora - timedelta(hours=1),
                article_count=5, source_count=5, is_flash=True,
                topic="lavoro_sindacati",
            )
            session.add(story2)
            await session.flush()
            for i, fonte in enumerate(prova):
                session.add(
                    Article(
                        source_id=fonte.id,
                        url=f"https://{fonte.domain}/sciopero",
                        title=f"Sciopero, versione n.{i} del titolo",
                        snippet="",
                        published_at=ora - timedelta(minutes=90 - i),
                        language="it",
                        story_id=story2.id,
                    )
                )
            await session.commit()
        await engine.dispose()

    asyncio.run(seed())


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="session")
def base_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    db_path = tmp_path_factory.mktemp("e2e") / "e2e.sqlite3"
    _seed_database(db_path)
    port = _free_port()
    env = os.environ | {
        "DATABASE_URL": f"sqlite+aiosqlite:///{db_path}",
        "SECRET_KEY": "e2e-secret",
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "apps.api.main:app", "--port", str(port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                if httpx.get(f"{url}/healthz", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.15)
        else:
            raise RuntimeError("il server e2e non è partito")
        yield url
    finally:
        proc.terminate()
        proc.wait(timeout=10)

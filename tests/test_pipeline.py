"""Orchestrazione parallela della raccolta (rete parallela, DB sequenziale)."""

from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from core.ingest.gdelt import GDELT_DOC_URL
from core.ingest.pipeline import ingest_all_feeds, ingest_gdelt_all
from core.ingest.ratelimit import DomainRateLimiter
from core.ingest.robots import RobotsCache
from core.ingest.rss import IngestStats
from core.models import Article, Source

FIXTURE_RSS = (Path(__file__).parent / "fixtures" / "feed_esempio.xml").read_bytes()


class FakeClock:
    def __init__(self) -> None:
        self.time = 0.0

    def now(self) -> float:
        return self.time

    async def sleep(self, seconds: float) -> None:
        self.time += seconds


def _limiter() -> DomainRateLimiter:
    clock = FakeClock()
    return DomainRateLimiter(min_interval=2.0, now=clock.now, sleep=clock.sleep)


def _fonte(slug: str, dominio: str, feeds: list[str], gdelt: str | None = None) -> Source:
    return Source(
        slug=slug, name=slug, domain=dominio, country="it", language="it",
        region="italy", feed_urls=feeds, gdelt_domain=gdelt, terms_note="",
    )


@pytest.fixture
def maker(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False)


@respx.mock
async def test_ingest_all_feeds_parallelo(maker: async_sessionmaker) -> None:
    async with maker() as session:
        session.add(_fonte("alfa", "alfa.test", ["https://alfa.test/rss.xml"]))
        session.add(_fonte("beta", "beta.test", ["https://beta.test/rss.xml"]))
        await session.commit()

    for host in ("alfa", "beta"):
        respx.get(f"https://{host}.test/robots.txt").mock(
            return_value=httpx.Response(404)
        )
        # URL articolo distinti per testata, altrimenti scatta il dedup.
        contenuto = FIXTURE_RSS.replace(b"esempio.test", f"{host}.test".encode())
        respx.get(f"https://{host}.test/rss.xml").mock(
            return_value=httpx.Response(200, content=contenuto)
        )

    progressi: list[tuple[str, str, IngestStats]] = []
    async with httpx.AsyncClient() as client:
        creati = await ingest_all_feeds(
            maker,
            client=client,
            limiter=_limiter(),
            robots=RobotsCache(client),
            progress=lambda s, u, st: progressi.append((s, u, st)),
        )

    assert creati == {"alfa": 2, "beta": 2}
    assert len(progressi) == 2
    async with maker() as session:
        articoli = list((await session.execute(select(Article))).scalars())
    assert len(articoli) == 4


def _gdelt_payload(*domini: str) -> dict:
    return {
        "articles": [
            {
                "url": f"https://{d}/articolo-{i}",
                "title": f"Titolo {d} {i}",
                "language": "English",
                "seendate": "20260827T120000Z",
                "domain": d,
            }
            for d in domini
            for i in range(2)
        ]
    }


@respx.mock
async def test_gdelt_batch_e_fonti_solo_gdelt(maker: async_sessionmaker) -> None:
    async with maker() as session:
        # Due fonti con feed (finiscono nel batch) e una solo-GDELT.
        session.add(_fonte("alfa", "alfa.test", ["https://alfa.test/rss.xml"], "alfa.test"))
        session.add(_fonte("beta", "beta.test", ["https://beta.test/rss.xml"], "beta.test"))
        session.add(_fonte("solo", "solo.test", [], "solo.test"))
        await session.commit()

    route = respx.get(GDELT_DOC_URL)

    def rispondi(request: httpx.Request) -> httpx.Response:
        query = request.url.params["query"]
        if "solo.test" in query:
            return httpx.Response(200, json=_gdelt_payload("solo.test"))
        return httpx.Response(200, json=_gdelt_payload("alfa.test", "www.beta.test"))

    route.side_effect = rispondi

    async with httpx.AsyncClient() as client:
        creati = await ingest_gdelt_all(maker, client=client, limiter=_limiter())

    # 2 richieste in tutto: una per la fonte solo-GDELT, una per il batch.
    assert len(route.calls) == 2
    assert creati == {"solo": 2, "alfa": 2, "beta": 2}
    query_batch = str(route.calls[1].request.url.params["query"])
    assert query_batch == "(domain:alfa.test OR domain:beta.test)"

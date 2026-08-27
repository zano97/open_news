"""Fase 1: client GDELT DOC 2.0 su fixture registrata, con provenance."""

import json
from pathlib import Path

import httpx
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core import provenance
from core.ingest.gdelt import GDELT_DOC_URL, ingest_gdelt_source, parse_artlist
from core.ingest.ratelimit import DomainRateLimiter
from core.models import Article, Source

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "gdelt_artlist.json").read_text()
)


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


def test_parse_artlist() -> None:
    articoli = parse_artlist(FIXTURE)
    # La voce senza titolo viene scartata.
    assert len(articoli) == 2
    primo = articoli[0]
    assert primo.language == "en"
    assert primo.seen_at is not None
    assert primo.seen_at.year == 2026
    assert primo.image_url is not None
    # socialimage vuota diventa None.
    assert articoli[1].image_url is None


@respx.mock
async def test_ingest_gdelt_con_provenance(session: AsyncSession) -> None:
    reuters = Source(
        slug="reuters",
        name="Reuters",
        domain="reuters.com",
        country="gb",
        language="en",
        region="world",
        feed_urls=[],
        gdelt_domain="reuters.com",
        terms_note="",
    )
    session.add(reuters)
    await session.flush()

    route = respx.get(GDELT_DOC_URL).mock(
        return_value=httpx.Response(200, json=FIXTURE)
    )
    async with httpx.AsyncClient() as client:
        created = await ingest_gdelt_source(
            session, reuters, client=client, limiter=_limiter()
        )
    assert created == 2
    assert route.calls[0].request.url.params["query"] == "domain:reuters.com"

    articoli = list((await session.execute(select(Article))).scalars())
    assert len(articoli) == 2
    # GDELT non fornisce estratti: lo snippet resta vuoto.
    assert all(a.snippet == "" for a in articoli)

    prova = await provenance.for_entity(session, "article", articoli[0].id)
    assert len(prova) == 1
    assert prova[0].method == "gdelt-doc-2.0"
    assert prova[0].source_name == "The GDELT Project"

    # Idempotenza: una seconda esecuzione non crea duplicati.
    async with httpx.AsyncClient() as client:
        created2 = await ingest_gdelt_source(
            session, reuters, client=client, limiter=_limiter()
        )
    assert created2 == 0

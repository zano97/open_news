"""Fase 1: ingestione RSS completa su fixture registrata (nessuna rete reale)."""

from pathlib import Path

import httpx
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.ingest.ratelimit import DomainRateLimiter
from core.ingest.robots import RobotsCache
from core.ingest.rss import ingest_feed, parse_feed
from core.models import Article, FeedState, Source

FIXTURE = (Path(__file__).parent / "fixtures" / "feed_esempio.xml").read_bytes()
FEED_URL = "https://esempio.test/rss.xml"


def _fonte() -> Source:
    return Source(
        slug="esempio",
        name="Quotidiano d'Esempio",
        domain="esempio.test",
        country="it",
        language="it",
        region="italy",
        feed_urls=[FEED_URL],
        terms_note="",
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


def test_parse_feed_fixture() -> None:
    entries = parse_feed(FIXTURE)
    # La voce senza titolo viene ignorata.
    assert len(entries) == 3
    prima = entries[0]
    assert prima.title.startswith("Il governo approva")
    assert prima.image_url == "https://esempio.test/img/pensioni.jpg"
    assert prima.published_at is not None
    assert prima.published_at.tzinfo is not None
    assert "Maria Rossi" in prima.authors[0]
    assert len(prima.snippet) <= 200
    assert "trattative" in prima.snippet


@respx.mock
async def test_ingest_dedup_e_cache_condizionale(session: AsyncSession) -> None:
    fonte = _fonte()
    session.add(fonte)
    await session.flush()

    respx.get("https://esempio.test/robots.txt").mock(return_value=httpx.Response(404))
    feed_route = respx.get(FEED_URL).mock(
        return_value=httpx.Response(
            200, content=FIXTURE, headers={"ETag": '"v1"', "Last-Modified": "oggi"}
        )
    )

    async with httpx.AsyncClient() as client:
        robots = RobotsCache(client)
        stats = await ingest_feed(
            session, fonte, FEED_URL, client=client, limiter=_limiter(), robots=robots
        )
        assert stats.fetched == 3
        # Il secondo item è lo stesso articolo con utm diversi: dedup da URL canonico.
        assert stats.created == 2
        assert stats.skipped_existing == 1

        articoli = list((await session.execute(select(Article))).scalars())
        assert len(articoli) == 2
        assert all(a.language == "it" for a in articoli)
        assert all(a.simhash for a in articoli)
        assert all(len(a.snippet) <= 200 for a in articoli)

        stato = (
            await session.execute(select(FeedState).where(FeedState.feed_url == FEED_URL))
        ).scalar_one()
        assert stato.etag == '"v1"'
        assert stato.last_status == 200

        # Seconda esecuzione: il server risponde 304 alla richiesta condizionale.
        feed_route.mock(return_value=httpx.Response(304))
        stats2 = await ingest_feed(
            session, fonte, FEED_URL, client=client, limiter=_limiter(), robots=robots
        )
        assert stats2.not_modified
        assert stats2.created == 0
        condizionale = feed_route.calls[-1].request
        assert condizionale.headers["If-None-Match"] == '"v1"'
        assert condizionale.headers["If-Modified-Since"] == "oggi"


@respx.mock
async def test_robots_vieta_il_feed(session: AsyncSession) -> None:
    fonte = _fonte()
    session.add(fonte)
    await session.flush()

    respx.get("https://esempio.test/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /")
    )
    async with httpx.AsyncClient() as client:
        stats = await ingest_feed(
            session,
            fonte,
            FEED_URL,
            client=client,
            limiter=_limiter(),
            robots=RobotsCache(client),
        )
    assert stats.error is not None
    assert "robots" in stats.error
    assert stats.created == 0


@respx.mock
async def test_errore_http_registrato(session: AsyncSession) -> None:
    fonte = _fonte()
    session.add(fonte)
    await session.flush()

    respx.get("https://esempio.test/robots.txt").mock(return_value=httpx.Response(404))
    respx.get(FEED_URL).mock(return_value=httpx.Response(500))
    async with httpx.AsyncClient() as client:
        stats = await ingest_feed(
            session,
            fonte,
            FEED_URL,
            client=client,
            limiter=_limiter(),
            robots=RobotsCache(client),
        )
    assert stats.error == "HTTP 500"
    stato = (
        await session.execute(select(FeedState).where(FeedState.feed_url == FEED_URL))
    ).scalar_one()
    assert stato.last_status == 500
    assert stato.error == "HTTP 500"


HOMEPAGE = """<!doctype html><html><head>
<link rel="alternate" type="application/rss+xml" title="Feed" href="/nuovo.xml">
</head><body>giornale</body></html>"""


@respx.mock
async def test_autodiscovery_su_404(session: AsyncSession) -> None:
    """URL del catalogo morto: il feed vero viene trovato dalla homepage
    e ricordato in FeedState.resolved_url."""
    fonte = _fonte()
    session.add(fonte)
    await session.flush()

    respx.get("https://esempio.test/robots.txt").mock(return_value=httpx.Response(404))
    respx.get(FEED_URL).mock(return_value=httpx.Response(404))
    respx.get("https://esempio.test/").mock(
        return_value=httpx.Response(200, text=HOMEPAGE)
    )
    nuovo = respx.get("https://esempio.test/nuovo.xml").mock(
        return_value=httpx.Response(200, content=FIXTURE)
    )

    async with httpx.AsyncClient() as client:
        robots = RobotsCache(client)
        stats = await ingest_feed(
            session, fonte, FEED_URL, client=client, limiter=_limiter(), robots=robots
        )
        assert stats.error is None
        assert stats.created == 2

        stato = (
            await session.execute(select(FeedState).where(FeedState.feed_url == FEED_URL))
        ).scalar_one()
        assert stato.resolved_url == "https://esempio.test/nuovo.xml"
        assert stato.consecutive_failures == 0

        # Dal secondo giro si interroga direttamente l'URL risolto.
        prima = len(nuovo.calls)
        await ingest_feed(
            session, fonte, FEED_URL, client=client, limiter=_limiter(), robots=robots
        )
        assert len(nuovo.calls) == prima + 1


@respx.mock
async def test_autodiscovery_su_pagina_html(session: AsyncSession) -> None:
    """URL che risponde 200 ma con una pagina HTML (es. indice dei feed):
    si passa al feed dichiarato nella pagina."""
    fonte = _fonte()
    session.add(fonte)
    await session.flush()

    respx.get("https://esempio.test/robots.txt").mock(return_value=httpx.Response(404))
    respx.get(FEED_URL).mock(
        return_value=httpx.Response(
            200, text=HOMEPAGE, headers={"content-type": "text/html"}
        )
    )
    respx.get("https://esempio.test/").mock(
        return_value=httpx.Response(200, text=HOMEPAGE)
    )
    respx.get("https://esempio.test/nuovo.xml").mock(
        return_value=httpx.Response(200, content=FIXTURE)
    )

    async with httpx.AsyncClient() as client:
        stats = await ingest_feed(
            session, fonte, FEED_URL,
            client=client, limiter=_limiter(), robots=RobotsCache(client),
        )
    assert stats.created == 2


@respx.mock
async def test_backoff_dopo_errori_ripetuti(session: AsyncSession) -> None:
    fonte = _fonte()
    session.add(fonte)
    await session.flush()

    respx.get("https://esempio.test/robots.txt").mock(return_value=httpx.Response(404))
    route = respx.get(FEED_URL).mock(return_value=httpx.Response(500))

    async with httpx.AsyncClient() as client:
        robots = RobotsCache(client)
        for _ in range(3):
            stats = await ingest_feed(
                session, fonte, FEED_URL,
                client=client, limiter=_limiter(), robots=robots,
            )
            assert stats.error == "HTTP 500"
        chiamate = len(route.calls)

        # Senza retry_failed il feed è in pausa: nessuna richiesta HTTP.
        stats = await ingest_feed(
            session, fonte, FEED_URL,
            client=client, limiter=_limiter(), robots=robots, retry_failed=False,
        )
        assert stats.backoff
        assert len(route.calls) == chiamate

        # Il seed (retry_failed=True) invece riprova sempre.
        stats = await ingest_feed(
            session, fonte, FEED_URL,
            client=client, limiter=_limiter(), robots=robots,
        )
        assert not stats.backoff
        assert len(route.calls) == chiamate + 1

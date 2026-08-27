"""Fase 1: download del testo integrale (interno, mai esposto) con robots e rate limit."""

import httpx
import respx
from sqlalchemy.ext.asyncio import AsyncSession

from core.extract.fulltext import articles_missing_fulltext, fetch_fulltext
from core.ingest.ratelimit import DomainRateLimiter
from core.ingest.robots import RobotsCache
from core.models import Article, Source

PAGINA = """
<html><body><article>
<p>Questo è il primo paragrafo dell'articolo di prova, con abbastanza testo
perché trafilatura lo riconosca come contenuto principale della pagina.</p>
<p>Un secondo paragrafo per dare ulteriore corpo al contenuto estratto
dall'articolo durante il test dell'ingestione del testo integrale.</p>
</article></body></html>
"""


class FakeClock:
    def __init__(self) -> None:
        self.time = 0.0

    def now(self) -> float:
        return self.time

    async def sleep(self, seconds: float) -> None:
        self.time += seconds


async def _articolo(session: AsyncSession, url: str) -> Article:
    fonte = Source(
        slug="esempio-ft",
        name="Esempio",
        domain="esempio.test",
        country="it",
        language="it",
        region="italy",
        feed_urls=[],
        terms_note="",
    )
    session.add(fonte)
    await session.flush()
    articolo = Article(source_id=fonte.id, url=url, title="Titolo", snippet="s")
    session.add(articolo)
    await session.flush()
    return articolo


@respx.mock
async def test_fetch_e_salva(session: AsyncSession) -> None:
    articolo = await _articolo(session, "https://esempio.test/articolo-lungo")
    respx.get("https://esempio.test/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://esempio.test/articolo-lungo").mock(
        return_value=httpx.Response(200, text=PAGINA)
    )
    clock = FakeClock()
    limiter = DomainRateLimiter(min_interval=2.0, now=clock.now, sleep=clock.sleep)
    async with httpx.AsyncClient() as client:
        ok = await fetch_fulltext(
            session, articolo, client=client, limiter=limiter, robots=RobotsCache(client)
        )
    assert ok
    assert articolo.full_text is not None
    assert "primo paragrafo" in articolo.full_text
    # Ora non compare più tra i mancanti.
    assert await articles_missing_fulltext(session) == []


@respx.mock
async def test_robots_blocca_il_fulltext(session: AsyncSession) -> None:
    articolo = await _articolo(session, "https://esempio.test/riservato")
    respx.get("https://esempio.test/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /riservato")
    )
    clock = FakeClock()
    limiter = DomainRateLimiter(min_interval=2.0, now=clock.now, sleep=clock.sleep)
    async with httpx.AsyncClient() as client:
        ok = await fetch_fulltext(
            session, articolo, client=client, limiter=limiter, robots=RobotsCache(client)
        )
    assert not ok
    assert articolo.full_text is None
    # Resta in coda tra i mancanti.
    mancanti = await articles_missing_fulltext(session)
    assert [a.id for a in mancanti] == [articolo.id]

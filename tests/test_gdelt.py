"""Fase 1: client GDELT DOC 2.0 su fixture registrata, con provenance."""

import json
from pathlib import Path

import httpx
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core import provenance
from core.ingest.gdelt import (
    GDELT_DOC_URL,
    fetch_domain_articles,
    ingest_gdelt_source,
    parse_artlist,
)
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


@respx.mock
async def test_retry_su_429() -> None:
    """Un 429 non è un fallimento: si attende e si riprova."""
    route = respx.get(GDELT_DOC_URL)
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "7"}),
        httpx.Response(200, json=FIXTURE),
    ]
    attese: list[float] = []

    async def sleep(secondi: float) -> None:
        attese.append(secondi)

    async with httpx.AsyncClient() as client:
        articoli = await fetch_domain_articles(
            client, _limiter(), "reuters.com", sleep=sleep
        )
    assert len(articoli) == 2
    assert len(route.calls) == 2
    assert attese == [7.0]  # Retry-After rispettato


@respx.mock
async def test_risposta_non_json_e_errore_leggibile(session: AsyncSession) -> None:
    """GDELT sotto carico risponde 200 con testo semplice: niente crash,
    zero articoli, errore spiegato nei log."""
    respx.get(GDELT_DOC_URL).mock(
        return_value=httpx.Response(200, text="Rate limit exceeded, slow down.")
    )
    fonte = Source(
        slug="reuters2", name="Reuters", domain="reuters.com",
        country="gb", language="en", region="world",
        feed_urls=[], gdelt_domain="reuters.com", terms_note="",
    )
    session.add(fonte)
    await session.flush()
    async with httpx.AsyncClient() as client:
        creati = await ingest_gdelt_source(
            session, fonte, client=client, limiter=_limiter()
        )
    assert creati == 0


def test_match_source_per_dominio() -> None:
    from core.ingest.gdelt import GdeltArticle, match_source

    fonti = [
        Source(slug="reuters", name="R", domain="reuters.com", country="gb",
               language="en", region="world", feed_urls=[],
               gdelt_domain="reuters.com", terms_note=""),
        Source(slug="g1", name="g1", domain="g1.globo.com", country="br",
               language="pt", region="world", feed_urls=[],
               gdelt_domain="g1.globo.com", terms_note=""),
    ]

    def art(dominio: str) -> GdeltArticle:
        return GdeltArticle(
            url=f"https://{dominio}/x", title="t", language=None,
            seen_at=None, image_url=None, domain=dominio, source_country=None,
        )

    assert match_source(art("www.reuters.com"), fonti) is fonti[0]
    assert match_source(art("reuters.com"), fonti) is fonti[0]
    assert match_source(art("g1.globo.com"), fonti) is fonti[1]
    # Nessun match parziale ingannevole: globo.com NON è g1.globo.com.
    assert match_source(art("globo.com"), fonti) is None
    assert match_source(art("altro.example"), fonti) is None


@respx.mock
async def test_query_batch_con_or() -> None:
    from core.ingest.gdelt import fetch_domains_articles

    route = respx.get(GDELT_DOC_URL).mock(return_value=httpx.Response(200, json=FIXTURE))
    async with httpx.AsyncClient() as client:
        await fetch_domains_articles(
            client, _limiter(), ["reuters.com", "apnews.com"]
        )
    query = route.calls[0].request.url.params["query"]
    assert query == "(domain:reuters.com OR domain:apnews.com)"


def test_tidy_title_ricompone_la_punteggiatura() -> None:
    from core.ingest.gdelt import tidy_title

    assert tidy_title("Trial date set for alleged 9 / 11 mastermind") == \
        "Trial date set for alleged 9/11 mastermind"
    assert tidy_title("Yayoi Kusama è morta , addio alla regina") == \
        "Yayoi Kusama è morta, addio alla regina"
    assert tidy_title("Meteo : allerta ( rossa ) in tre regioni !") == \
        "Meteo: allerta (rossa) in tre regioni!"

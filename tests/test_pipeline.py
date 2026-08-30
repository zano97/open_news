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


@respx.mock
async def test_gdelt_secondo_passaggio_sui_falliti(maker: async_sessionmaker) -> None:
    """Connessioni perse verso GDELT: il gruppo fallito viene ritentato a
    fine giro invece di perdere la copertura."""
    async with maker() as session:
        session.add(_fonte("solo", "solo.test", [], "solo.test"))
        await session.commit()

    route = respx.get(GDELT_DOC_URL)
    route.side_effect = [
        httpx.ConnectTimeout("persa"),
        httpx.ConnectTimeout("persa"),
        httpx.ConnectTimeout("persa"),
        httpx.Response(200, json=_gdelt_payload("solo.test")),
    ]

    async def niente_attesa(_secondi: float) -> None:
        return None

    async with httpx.AsyncClient() as client:
        creati = await ingest_gdelt_all(
            maker, client=client, limiter=_limiter(), sleep=niente_attesa
        )

    assert len(route.calls) == 4  # 3 tentativi + 1 del secondo passaggio
    assert creati == {"solo": 2}


@respx.mock
async def test_gdelt_interruttore_quando_irraggiungibile(
    maker: async_sessionmaker,
) -> None:
    """GDELT giù: dopo 2 gruppi consecutivi senza connessione i rimanenti
    si saltano subito (niente minuti persi), secondo passaggio compreso."""
    async with maker() as session:
        for slug in ("uno", "due", "tre"):
            session.add(_fonte(slug, f"{slug}.test", [], f"{slug}.test"))
        await session.commit()

    route = respx.get(GDELT_DOC_URL)
    route.side_effect = [httpx.ConnectTimeout("giù")] * 4  # 2 tentativi x 2 gruppi

    async def niente_attesa(_secondi: float) -> None:
        return None

    async with httpx.AsyncClient() as client:
        creati = await ingest_gdelt_all(
            maker, client=client, limiter=_limiter(), sleep=niente_attesa
        )

    assert len(route.calls) == 4  # il terzo gruppo non viene nemmeno tentato
    assert creati == {}


@respx.mock
async def test_intero_catalogo_reale_scaricabile(maker: async_sessionmaker) -> None:
    """Prova generale del primo scaricamento sull'INTERO catalogo vero:
    ogni feed risponde (rete simulata), ogni fonte abilitata con feed deve
    produrre articoli, nessuna eccezione, e — usando il client con guardia
    egress — ogni URL del catalogo deve essere dentro l'allowlist."""
    from core.ingest.catalog import sync_catalog
    from core.net import build_client, reset_allowlist_cache

    reset_allowlist_cache()
    async with maker() as session:
        await sync_catalog(session)
        await session.commit()

    def feed_su_misura(request: httpx.Request) -> httpx.Response:
        # Un piccolo feed valido, con titoli e URL unici per host+percorso
        # (altrimenti il dedup globale li collasserebbe).
        base = f"https://{request.url.host}{request.url.path}"
        firma = f"{request.url.host}{request.url.path}".replace("/", " ")
        items = "".join(
            f"<item><title>Notizia {'molto ' * i}particolare {i} da {firma}</title>"
            f"<link>{base}?voce={i}</link>"
            f"<description>Estratto {i} di prova.</description></item>"
            for i in range(3)
        )
        rss = (
            "<?xml version='1.0'?><rss version='2.0'><channel>"
            f"<title>{firma}</title>{items}</channel></rss>"
        )
        return httpx.Response(200, content=rss.encode())

    respx.get(GDELT_DOC_URL).mock(
        return_value=httpx.Response(200, json={"articles": []})
    )
    respx.route(method="GET", path__regex=r"/robots\.txt$").mock(
        return_value=httpx.Response(404)
    )
    respx.route(method="GET").mock(side_effect=feed_su_misura)

    async with build_client() as client:
        creati = await ingest_all_feeds(
            maker,
            client=client,
            limiter=_limiter(),
            robots=RobotsCache(client),
            max_feeds_per_source=4,
        )
        await ingest_gdelt_all(maker, client=client, limiter=_limiter())

    async with maker() as session:
        con_feed = [
            s for s in (await session.execute(select(Source).where(Source.enabled))).scalars()
            if s.feed_urls
        ]
    assert len(con_feed) >= 60
    for fonte in con_feed:
        assert creati.get(fonte.slug, 0) >= 1, f"{fonte.slug}: nessun articolo"


@respx.mock
async def test_tutto_fallisce_ma_niente_crash(maker: async_sessionmaker) -> None:
    """Scenario catastrofico: ogni feed è rotto e GDELT è giù. La raccolta
    deve finire senza eccezioni (l'installazione non si blocca mai)."""
    async with maker() as session:
        session.add(_fonte("a", "a.test", ["https://a.test/rss.xml"], "a.test"))
        session.add(_fonte("b", "b.test", ["https://b.test/rss.xml"], "b.test"))
        session.add(_fonte("c", "c.test", [], "c.test"))
        await session.commit()

    respx.route(method="GET", path__regex=r"/robots\.txt$").mock(
        return_value=httpx.Response(404)
    )
    respx.get("https://a.test/rss.xml").mock(return_value=httpx.Response(500))
    respx.get("https://b.test/rss.xml").mock(
        side_effect=httpx.ConnectError("rete assente")
    )
    respx.get("https://a.test/").mock(return_value=httpx.Response(500))
    respx.get("https://b.test/").mock(side_effect=httpx.ConnectError("rete assente"))
    respx.get(GDELT_DOC_URL).mock(side_effect=httpx.ConnectTimeout("giù"))

    async def niente_attesa(_secondi: float) -> None:
        return None

    async with httpx.AsyncClient() as client:
        creati_feed = await ingest_all_feeds(
            maker, client=client, limiter=_limiter(), robots=RobotsCache(client),
            retry_failed=True,
        )
        creati_gdelt = await ingest_gdelt_all(
            maker, client=client, limiter=_limiter(), sleep=niente_attesa
        )

    assert creati_feed == {"a": 0, "b": 0}
    assert creati_gdelt == {}


def test_i_job_di_raccolta_partono_subito_all_avvio() -> None:
    """Chi apre l'app per pochi minuti deve vedere notizie fresche: i job
    di raccolta hanno un next_run_time entro pochi minuti dall'avvio, non
    dopo il primo intervallo pieno."""
    from datetime import datetime, timedelta

    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    from apps.worker.jobs import register_jobs

    scheduler = AsyncIOScheduler(timezone="UTC")
    register_jobs(scheduler)
    limite = datetime.now(scheduler.timezone) + timedelta(minutes=6)
    for job_id in ("ingest_feeds", "ingest_gdelt", "cluster"):
        job = next(j for j in scheduler.get_jobs() if j.id == job_id)
        assert job.next_run_time is not None and job.next_run_time <= limite, job_id


@respx.mock
async def test_un_feed_avvelenato_non_ammazza_la_flotta(
    maker: async_sessionmaker,
) -> None:
    """Un'eccezione INATTESA su un feed non deve far uscire dal giro: prima
    il client veniva chiuso sotto i task ancora in volo («Cannot send a
    request, as the client has been closed») e gli articoli delle altre
    testate andavano persi. Ora il feed rotto si salta, la flotta finisce,
    e nessun task resta orfano."""
    async with maker() as session:
        session.add(_fonte("sana-a", "sana-a.test", ["https://sana-a.test/rss.xml"]))
        session.add(_fonte("rotta", "rotta.test", ["https://rotta.test/rss.xml"]))
        session.add(_fonte("sana-b", "sana-b.test", ["https://sana-b.test/rss.xml"]))
        await session.commit()

    for host in ("sana-a", "rotta", "sana-b"):
        respx.get(f"https://{host}.test/robots.txt").mock(
            return_value=httpx.Response(404)
        )
    for host in ("sana-a", "sana-b"):
        contenuto = FIXTURE_RSS.replace(b"esempio.test", f"{host}.test".encode())
        respx.get(f"https://{host}.test/rss.xml").mock(
            return_value=httpx.Response(200, content=contenuto)
        )

    def esplode(request: httpx.Request) -> httpx.Response:
        raise ValueError("feed avvelenato: eccezione inattesa")

    respx.get("https://rotta.test/rss.xml").mock(side_effect=esplode)

    async with httpx.AsyncClient() as client:
        creati = await ingest_all_feeds(
            maker,
            client=client,
            limiter=_limiter(),
            robots=RobotsCache(client),
        )

    # Le testate sane sono arrivate in fondo nonostante l'esplosione.
    assert creati.get("sana-a") == 2
    assert creati.get("sana-b") == 2
    async with maker() as session:
        articoli = list((await session.execute(select(Article))).scalars())
    assert len(articoli) == 4

"""OSINT sulle testate: ads.txt, trasparenza dichiarata, archivio, rete."""

import httpx
import respx
from sqlalchemy.ext.asyncio import AsyncSession

from core import provenance
from core.ingest.ratelimit import DomainRateLimiter
from core.ingest.robots import RobotsCache
from core.models import Source
from core.osint.adstxt import (
    AdsEntry,
    AdsProfile,
    conti_condivisi,
    fetch_ads_txt,
    parse_ads_txt,
)
from core.osint.trust import parse_trust_markup
from core.osint.wayback import prima_copia

ADS_TXT = """# ads.txt del Quotidiano d'Esempio
CONTACT=pubblicita@esempio.test
google.com, pub-0001, DIRECT, f08c47fec0942fa0
appnexus.com, 4242, RESELLER
criteo.com, 99, direct
riga, incompleta
google.com, pub-0001, DIRECT
"""

HOMEPAGE_TRUST = """<!doctype html><html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@graph":[
 {"@type":"WebSite","name":"sito"},
 {"@type":"NewsMediaOrganization","name":"Quotidiano d'Esempio",
  "foundingDate":"1901-11-05",
  "ownershipFundingInfo":"https://esempio.test/proprieta",
  "ethicsPolicy":{"@type":"CreativeWork","url":"https://esempio.test/etica"},
  "correctionsPolicy":"https://esempio.test/rettifiche",
  "masthead":"https://esempio.test/redazione",
  "parentOrganization":{"@type":"Organization","name":"Editrice Esempio SpA"}}]}
</script></head><body><p>giornale</p></body></html>"""


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


def _fonte(slug: str = "esempio-osint", domain: str = "esempio.test") -> Source:
    return Source(
        slug=slug, name="Quotidiano d'Esempio", domain=domain, country="it",
        language="it", region="italy", feed_urls=[], gdelt_domain=domain,
        terms_note="",
    )


def test_parse_ads_txt() -> None:
    voci = parse_ads_txt(ADS_TXT)
    # Commenti, variabili, righe corte e duplicati restano fuori.
    assert voci == [
        AdsEntry("google.com", "pub-0001", "direct"),
        AdsEntry("appnexus.com", "4242", "reseller"),
        AdsEntry("criteo.com", "99", "direct"),
    ]
    profilo = AdsProfile(url="x", entries=voci)
    assert profilo.reti() == ["appnexus.com", "criteo.com", "google.com"]
    # I rapporti "reseller" non sono conti dell'editore.
    assert [e.exchange for e in profilo.diretti] == ["google.com", "criteo.com"]


def test_conti_condivisi_sono_indizi_di_rete() -> None:
    """Due testate col MEDESIMO conto diretto condividono il conto
    economico: è l'indizio pubblico più forte di gestione comune."""
    profili = {
        "alfa": AdsProfile("a", [AdsEntry("google.com", "pub-1", "direct")]),
        "beta": AdsProfile("b", [AdsEntry("google.com", "pub-1", "direct")]),
        "gamma": AdsProfile("c", [AdsEntry("google.com", "pub-9", "direct")]),
        # Stesso id ma come RIVENDITORE: è un intermediario, non un conto.
        "delta": AdsProfile("d", [AdsEntry("google.com", "pub-1", "reseller")]),
    }
    gruppi = conti_condivisi(profili)
    assert gruppi == [
        {"rete": "google.com", "id": "pub-1", "testate": ["alfa", "beta"]}
    ]


def test_parse_trust_markup() -> None:
    profilo = parse_trust_markup(HOMEPAGE_TRUST)
    assert profilo.nome_dichiarato == "Quotidiano d'Esempio"
    assert profilo.fondazione == "1901-11-05"
    assert profilo.editore == "Editrice Esempio SpA"
    assert profilo.punteggio == 4
    assert profilo.impegni["codice_etico"] == "https://esempio.test/etica"
    assert profilo.impegni["redazione"] == "https://esempio.test/redazione"


def test_trust_markup_assente() -> None:
    profilo = parse_trust_markup("<html><body>niente dati strutturati</body></html>")
    assert profilo.punteggio == 0
    assert profilo.error


@respx.mock
async def test_fetch_ads_txt_assente() -> None:
    """Un 404 è un esito («non dichiara venditori»), non un errore."""
    respx.get("https://esempio.test/ads.txt").mock(return_value=httpx.Response(404))
    async with httpx.AsyncClient() as client:
        profilo = await fetch_ads_txt("esempio.test", client=client, limiter=_limiter())
    assert profilo.error == "assente"
    assert profilo.entries == []


@respx.mock
async def test_prima_copia_archiviata() -> None:
    respx.get("https://web.archive.org/cdx/search/cdx").mock(
        return_value=httpx.Response(
            200, json=[["timestamp"], ["19981212235959"]]
        )
    )
    async with httpx.AsyncClient() as client:
        data = await prima_copia("esempio.test", client=client, limiter=_limiter())
    assert data == "1998-12-12"


@respx.mock
async def test_profilo_completo_con_provenance(session: AsyncSession) -> None:
    from core.osint.profile import profila_fonte, rete_di_conti

    fonte = _fonte()
    session.add(fonte)
    await session.flush()

    respx.get("https://esempio.test/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://esempio.test/ads.txt").mock(
        return_value=httpx.Response(200, text=ADS_TXT)
    )
    respx.get("https://esempio.test/").mock(
        return_value=httpx.Response(200, text=HOMEPAGE_TRUST)
    )
    respx.get("https://web.archive.org/cdx/search/cdx").mock(
        return_value=httpx.Response(200, json=[["timestamp"], ["20010704120000"]])
    )

    async with httpx.AsyncClient() as client:
        profilo = await profila_fonte(
            session, fonte, client=client, limiter=_limiter(),
            robots=RobotsCache(client),
        )

    assert profilo["pubblicita"]["reti"] == [
        "appnexus.com", "criteo.com", "google.com"
    ]
    assert profilo["trasparenza"]["punteggio"] == 4
    assert profilo["trasparenza"]["editore_dichiarato"] == "Editrice Esempio SpA"
    assert profilo["prima_copia_archiviata"] == "2001-07-04"
    assert fonte.osint["trasparenza"]["nome_dichiarato"] == "Quotidiano d'Esempio"
    assert fonte.last_checked_at is not None

    # Ogni raccolta lascia la sua provenance, con l'URL dell'evidenza.
    prova = await provenance.for_entity(session, "source", fonte.id)
    riga = next(p for p in prova if p.field == "osint")
    assert riga.method == "osint-fonti-v1"
    assert riga.source_url == "https://esempio.test/ads.txt"

    # La rete si calcola dai profili salvati, senza toccare la rete.
    gemella = _fonte(slug="gemella", domain="gemella.test")
    gemella.osint = {
        "pubblicita": {
            "url": "https://gemella.test/ads.txt",
            "conti_diretti": [{"rete": "google.com", "id": "pub-0001"}],
        }
    }
    session.add(gemella)
    await session.flush()
    gruppi = await rete_di_conti(session)
    assert gruppi == [
        {
            "rete": "google.com",
            "id": "pub-0001",
            "testate": ["esempio-osint", "gemella"],
        }
    ]


@respx.mock
async def test_robots_governa_le_pagine_non_i_feed(session: AsyncSession) -> None:
    """La homepage è navigazione: se robots.txt la vieta, non si tocca
    (i FEED restano esenti, ADR-0025; le PAGINE no, ADR-0027)."""
    from core.osint.fetch import scarica_pagina

    respx.get("https://esempio.test/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /")
    )
    home = respx.get("https://esempio.test/").mock(
        return_value=httpx.Response(200, text=HOMEPAGE_TRUST)
    )
    async with httpx.AsyncClient() as client:
        pagina = await scarica_pagina(
            "https://esempio.test/", client=client, limiter=_limiter(),
            robots=RobotsCache(client),
        )
    assert not pagina.ok
    assert pagina.error is not None and "robots" in pagina.error
    assert not home.called


def test_nessuna_elusione_antibot() -> None:
    """Scelta esplicita e verificata: Scrapling serve a RENDERIZZARE
    pagine pubbliche, mai ad aggirare una protezione (ADR-0027)."""
    from pathlib import Path

    from core.osint import fetch

    assert fetch.BYPASS_ANTIBOT is False
    codice = Path(fetch.__file__).read_text(encoding="utf-8")
    for vietato in ("solve_cloudflare", "StealthyFetcher", "google_search"):
        assert vietato not in codice.split('"""', 2)[-1], vietato


def test_senza_scrapling_il_sistema_funziona() -> None:
    """L'extra [osint] è opzionale: senza, si usa il client di sempre."""
    from core.osint.fetch import reset_scrapling_cache, scrapling_disponibile

    reset_scrapling_cache()
    # Nell'ambiente di test scrapling non è installato: nessuna eccezione.
    assert scrapling_disponibile() in (True, False)
    reset_scrapling_cache()


def test_internet_archive_in_allowlist_ma_non_il_resto() -> None:
    from core.net import host_allowed, reset_allowlist_cache

    reset_allowlist_cache()
    assert host_allowed("web.archive.org")
    assert not host_allowed("api.opencorporates.com")  # servizio a chiave
    reset_allowlist_cache()


async def test_scheda_fonte_avvia_la_raccolta_su_richiesta(
    client: httpx.AsyncClient, session: AsyncSession, monkeypatch
) -> None:
    """Aprire la scheda di una testata senza profilo avvia SUBITO la
    raccolta: con 170 testate, aspettare il giro di sfondo significava
    vedere «non ancora raccolto» per giorni."""
    from core.osint import profile as modulo

    fonte = _fonte(slug="on-demand", domain="ondemand.test")
    session.add(fonte)
    await session.commit()

    chiamate: list[str] = []

    def finto_kick(slug: str) -> None:
        chiamate.append(slug)
        modulo._KICK_IN_CORSO.add(slug)  # come il vero: segna «in corso»

    monkeypatch.setattr(modulo, "kick_profilo", finto_kick)
    try:
        pagina = await client.get("/fonte/on-demand")
        assert pagina.status_code == 200
        assert chiamate == ["on-demand"]
        # In pagina il lettore legge «in corso», non «non ancora raccolto».
        assert "data-osint-in-corso" in pagina.text
    finally:
        modulo._KICK_IN_CORSO.discard("on-demand")

    # Con un profilo già RIUSCITO non si richiede nulla.
    fonte.osint = {
        "aggiornato_il": "2026-08-28T10:00:00+00:00",
        "pubblicita": {"stato": "letto", "reti": ["google.com"]},
    }
    await session.commit()
    chiamate.clear()
    pagina = await client.get("/fonte/on-demand")
    assert chiamate == []
    assert "data-osint-in-corso" not in pagina.text


async def test_conteggio_profili(session: AsyncSession) -> None:
    from core.osint.profile import conteggio_profili

    con = _fonte(slug="con-profilo", domain="a.test")
    con.osint = {"aggiornato_il": "2026-08-28T10:00:00+00:00"}
    senza = _fonte(slug="senza-profilo", domain="b.test")
    session.add_all([con, senza])
    await session.flush()
    assert await conteggio_profili(session) == (1, 2)


def test_profilo_vuoto_si_ritenta_presto() -> None:
    """Un tentativo andato a vuoto (rete assente) non deve bloccare la
    testata per due settimane; un ads.txt semplicemente ASSENTE, invece,
    è un esito valido e non va rimartellato."""
    from datetime import timedelta

    from core.models import utcnow
    from core.osint.profile import _da_rinfrescare, profilo_vuoto

    adesso = utcnow()
    fallito = {
        "aggiornato_il": (adesso - timedelta(hours=7)).isoformat(),
        "pubblicita": {"stato": "ProxyError", "reti": []},
        "trasparenza": {"errore": "ProxyError"},
    }
    assert profilo_vuoto(fallito)
    fonte = _fonte()
    fonte.osint = fallito
    assert _da_rinfrescare(fonte, adesso)  # dopo 6 ore si riprova

    fonte.osint = {**fallito, "aggiornato_il": (adesso - timedelta(hours=2)).isoformat()}
    assert not _da_rinfrescare(fonte, adesso)  # ma non subito

    riuscito = {
        "aggiornato_il": (adesso - timedelta(days=2)).isoformat(),
        "pubblicita": {"stato": "assente", "reti": []},
        "trasparenza": {"errore": "nessun dato strutturato"},
    }
    assert not profilo_vuoto(riuscito)  # "assente" è un esito, non un errore
    fonte.osint = riuscito
    assert not _da_rinfrescare(fonte, adesso)

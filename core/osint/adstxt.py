"""ads.txt: chi è autorizzato a vendere la pubblicità di una testata.

`/ads.txt` è uno standard IAB che ogni editore pubblica sul proprio
dominio per dichiarare quali società possono vendere il suo spazio
pubblicitario, con l'ID dell'account presso ciascuna. È informazione
pubblicata APPOSTA per essere letta da macchine.

Perché ci serve: la letteratura sull'ecosistema pubblicitario usa
ads.txt per due cose che riguardano da vicino il nostro scopo —
(1) capire **chi finanzia** una testata (quali reti la monetizzano), e
(2) far emergere **reti di siti gestiti dalla stessa entità**: due
domini «indipendenti» che dichiarano lo STESSO id di publisher presso
la stessa rete condividono, di fatto, lo stesso conto economico.

Resta un indizio, mai un verdetto: si mostra l'evidenza (riga di
ads.txt, URL) e si lascia al lettore la conclusione.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx

from core.ingest.ratelimit import DomainRateLimiter
from core.net import EgressDeniedError

log = logging.getLogger(__name__)

MAX_BYTES = 400_000
# Le reti che rivendono per conto di molti editori: un id condiviso qui
# non dice nulla sulla proprietà (è un intermediario, non un conto).
RESELLER_KEYWORD = "reseller"


@dataclass(frozen=True)
class AdsEntry:
    """Una riga di ads.txt: (dominio della rete, id dell'account, rapporto)."""

    exchange: str
    publisher_id: str
    relationship: str  # "direct" | "reseller"


@dataclass
class AdsProfile:
    url: str
    entries: list[AdsEntry] = field(default_factory=list)
    error: str | None = None

    @property
    def diretti(self) -> list[AdsEntry]:
        """Solo i rapporti DIRETTI: sono quelli che indicano un conto
        dell'editore presso la rete, non una rivendita di terzi."""
        return [e for e in self.entries if e.relationship == "direct"]

    def reti(self) -> list[str]:
        return sorted({e.exchange for e in self.entries})


def parse_ads_txt(testo: str) -> list[AdsEntry]:
    """Righe valide di un ads.txt: `dominio, id, RELAZIONE[, certid]`.

    Commenti (#), variabili (CONTACT=, SUBDOMAIN=) e righe malformate
    vengono ignorate senza rumore: i file reali sono pieni di entrambi.
    """
    entries: list[AdsEntry] = []
    visti: set[tuple[str, str, str]] = set()
    for riga in testo.splitlines():
        riga = riga.split("#", 1)[0].strip()
        if not riga or "=" in riga.split(",")[0]:
            continue
        campi = [c.strip() for c in riga.split(",")]
        if len(campi) < 3:
            continue
        exchange = campi[0].lower().removeprefix("www.")
        publisher_id = campi[1]
        relazione = campi[2].lower()
        if not exchange or "." not in exchange or not publisher_id:
            continue
        if relazione not in ("direct", "reseller"):
            continue
        chiave = (exchange, publisher_id, relazione)
        if chiave in visti:
            continue
        visti.add(chiave)
        entries.append(AdsEntry(exchange, publisher_id, relazione))
    return entries


async def fetch_ads_txt(
    domain: str, *, client: httpx.AsyncClient, limiter: DomainRateLimiter
) -> AdsProfile:
    """Scarica `https://<dominio>/ads.txt`. Un 404 è un esito, non un errore:
    significa «questa testata non dichiara venditori autorizzati»."""
    url = f"https://{domain}/ads.txt"
    profilo = AdsProfile(url=url)
    await limiter.wait(urlsplit(url).hostname or domain)
    try:
        resp = await client.get(url)
    except (httpx.HTTPError, EgressDeniedError) as exc:
        profilo.error = f"{exc.__class__.__name__}"
        return profilo
    if resp.status_code == 404:
        profilo.error = "assente"
        return profilo
    if resp.status_code != 200:
        profilo.error = f"HTTP {resp.status_code}"
        return profilo
    testo = resp.content[:MAX_BYTES].decode("utf-8", "replace")
    if "<html" in testo[:2000].lower():
        # Alcuni siti servono la pagina 404 con stato 200.
        profilo.error = "assente"
        return profilo
    profilo.entries = parse_ads_txt(testo)
    if not profilo.entries:
        profilo.error = "assente"
    return profilo


_ID_PULITO = re.compile(r"^[A-Za-z0-9_.\-]+$")


def conti_condivisi(
    profili: dict[str, AdsProfile], *, minimo: int = 1
) -> list[dict[str, Any]]:
    """Indizi di rete: gruppi di testate che dichiarano lo STESSO conto
    (rete + id) con rapporto DIRETTO.

    Un conto diretto condiviso significa che gli incassi pubblicitari
    delle testate finiscono sullo stesso account presso quella rete: è
    l'indizio più forte, tra quelli pubblici, di una gestione comune.
    I rapporti «reseller» sono esclusi (là l'id è dell'intermediario).
    """
    per_conto: dict[tuple[str, str], set[str]] = {}
    for slug, profilo in profili.items():
        for voce in profilo.diretti:
            if not _ID_PULITO.match(voce.publisher_id):
                continue
            per_conto.setdefault((voce.exchange, voce.publisher_id), set()).add(slug)
    gruppi: list[dict[str, Any]] = [
        {
            "rete": exchange,
            "id": publisher_id,
            "testate": sorted(slugs),
        }
        for (exchange, publisher_id), slugs in per_conto.items()
        if len(slugs) > minimo
    ]
    gruppi.sort(key=lambda g: (-len(g["testate"]), g["rete"]))
    return gruppi

"""Età reale di un sito secondo l'Internet Archive (CDX API, gratuita).

Serve a confrontare ciò che una testata DICHIARA con ciò che il web
ricorda: un quotidiano che si presenta come storico ma il cui sito
compare negli archivi da pochi mesi è un fatto che il lettore ha
diritto di sapere. Non è un verdetto — un dominio può cambiare —, è
una data con la sua evidenza.
"""

import logging

import httpx

from core.ingest.ratelimit import DomainRateLimiter
from core.net import EgressDeniedError

log = logging.getLogger(__name__)

CDX_HOST = "web.archive.org"
CDX_URL = f"https://{CDX_HOST}/cdx/search/cdx"


async def prima_copia(
    domain: str, *, client: httpx.AsyncClient, limiter: DomainRateLimiter
) -> str | None:
    """Data (AAAA-MM-GG) della prima copia archiviata del dominio, se c'è."""
    await limiter.wait(CDX_HOST)
    try:
        # Il CDX dell'Archive sa essere LENTO: meglio rinunciare in fretta
        # (ritenterà il giro) che tenere il profilo in ostaggio.
        resp = await client.get(
            CDX_URL,
            timeout=8.0,
            params={
                "url": domain,
                "output": "json",
                "fl": "timestamp",
                "filter": "statuscode:200",
                "limit": "1",
                "collapse": "urlkey",
            },
        )
        resp.raise_for_status()
        righe = resp.json()
    except (httpx.HTTPError, EgressDeniedError, ValueError) as exc:
        log.info("Internet Archive non raggiungibile per %s: %s", domain, exc)
        return None
    # La prima riga è l'intestazione delle colonne.
    if not isinstance(righe, list) or len(righe) < 2:
        return None
    timestamp = str(righe[1][0])
    if len(timestamp) < 8 or not timestamp[:8].isdigit():
        return None
    return f"{timestamp[:4]}-{timestamp[4:6]}-{timestamp[6:8]}"

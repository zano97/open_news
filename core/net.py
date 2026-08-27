"""Uscita di rete controllata: un solo punto di costruzione dei client HTTP.

Vincolo di progetto: nessuna chiamata verso servizi a pagamento. Ogni client
costruito qui rifiuta le richieste verso host fuori dall'allowlist, composta
da: infrastruttura gratuita documentata (GDELT, Wikidata, registri pubblici),
host interni allo stack (senza punto nel nome, localhost) e i domini delle
fonti del catalogo. Il test `tests/test_net.py` verifica il comportamento.
"""

import ipaddress
from functools import lru_cache
from urllib.parse import urlsplit

import httpx

from core.config import get_settings

# Infrastruttura gratuita e documentata (vedi NOTICE): suffissi di dominio.
STATIC_ALLOWED_SUFFIXES: frozenset[str] = frozenset(
    {
        "api.gdeltproject.org",  # GDELT DOC 2.0, senza chiave, con citazione
        "wikidata.org",  # fatti societari, CC0
        "dbpedia.org",  # entity linking di riserva
        "agcom.it",  # ROC — registro operatori di comunicazione
        "informazioneeditoria.gov.it",  # contributi diretti all'editoria
        "media-ownership.eu",  # EurOMo, CC BY 4.0
        "raw.githubusercontent.com",  # font OFL e asset vendorizzati (solo script di setup)
        "test",  # dominio riservato RFC 2606: usato solo nei test
    }
)


class EgressDeniedError(RuntimeError):
    """Richiesta verso un host fuori dall'allowlist: mai silenziata."""

    def __init__(self, host: str) -> None:
        super().__init__(
            f"richiesta HTTP verso host non in allowlist: {host!r}. "
            "Se è una nuova fonte, aggiungila a data/sources.yaml; se è un "
            "servizio, deve essere gratuito e documentato in core/net.py e NOTICE."
        )
        self.host = host


def _catalog_hosts() -> frozenset[str]:
    """Domini delle fonti dal catalogo (dominio testata + host dei feed)."""
    # Import locale per evitare dipendenze circolari con core.ingest.
    from core.ingest.catalog import load_catalog

    hosts: set[str] = set()
    for src in load_catalog():
        hosts.add(src.domain.lower())
        for feed in src.feed_urls:
            host = urlsplit(feed).hostname
            if host:
                hosts.add(host.lower())
    return frozenset(hosts)


@lru_cache(maxsize=1)
def allowed_suffixes() -> frozenset[str]:
    return STATIC_ALLOWED_SUFFIXES | _catalog_hosts()


def host_allowed(host: str) -> bool:
    host = host.lower().rstrip(".")
    # Host interni allo stack (meilisearch, ollama, db) e loopback.
    if host in {"localhost"} or "." not in host:
        return True
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return ipaddress.ip_address(host).is_private or ipaddress.ip_address(host).is_loopback
    return any(host == suffix or host.endswith("." + suffix) for suffix in allowed_suffixes())


async def _guard_request(request: httpx.Request) -> None:
    host = request.url.host
    if not host_allowed(host):
        raise EgressDeniedError(host)


def build_client(
    *,
    timeout: float | None = None,
    follow_redirects: bool = True,
) -> httpx.AsyncClient:
    """Client HTTP con User-Agent identificativo e guardia sull'egress.

    Tutto il codice del progetto che parla con l'esterno DEVE passare da qui.
    """
    settings = get_settings()
    return httpx.AsyncClient(
        headers={"User-Agent": settings.user_agent},
        timeout=timeout if timeout is not None else settings.http_timeout_seconds,
        follow_redirects=follow_redirects,
        event_hooks={"request": [_guard_request]},
    )


def reset_allowlist_cache() -> None:
    """Per test e per ricarichi del catalogo."""
    allowed_suffixes.cache_clear()

"""Fase 1: la guardia sull'egress blocca i domini fuori allowlist.

Questo è il test richiesto dalla definizione di "fatto" del progetto: nessuna
chiamata verso servizi non in allowlist (quindi nessun servizio a pagamento)
può partire dal codice, perché ogni client HTTP passa da core.net.build_client.
"""

import httpx
import pytest
import respx

from core.net import EgressDeniedError, build_client, host_allowed


class TestHostAllowed:
    def test_infrastruttura_gratuita(self) -> None:
        assert host_allowed("api.gdeltproject.org")
        assert host_allowed("query.wikidata.org")
        assert host_allowed("www.wikidata.org")

    def test_fonti_del_catalogo(self) -> None:
        assert host_allowed("www.repubblica.it")
        assert host_allowed("feeds.bbci.co.uk")
        assert host_allowed("rss.nytimes.com")

    def test_host_interni_allo_stack(self) -> None:
        assert host_allowed("meilisearch")  # nome di servizio compose, senza punto
        assert host_allowed("localhost")
        assert host_allowed("127.0.0.1")
        assert host_allowed("192.168.1.10")

    def test_servizi_esterni_negati(self) -> None:
        assert not host_allowed("api.openai.com")
        assert not host_allowed("newsapi.org")
        assert not host_allowed("evil.example.com")
        assert not host_allowed("8.8.8.8")  # IP pubblico

    def test_suffisso_non_ingannabile(self) -> None:
        # Un dominio che TERMINA con un dominio ammesso ma non ne è sottodominio.
        assert not host_allowed("fakewikidata.org")
        assert not host_allowed("wikidata.org.evil.com")


async def test_client_blocca_dominio_non_ammesso() -> None:
    async with build_client() as client:
        with pytest.raises(EgressDeniedError):
            await client.get("https://api.openai.com/v1/models")


@respx.mock
async def test_client_consente_dominio_ammesso() -> None:
    route = respx.get("https://api.gdeltproject.org/api/v2/doc/doc").mock(
        return_value=httpx.Response(200, json={"articles": []})
    )
    async with build_client() as client:
        resp = await client.get("https://api.gdeltproject.org/api/v2/doc/doc")
    assert resp.status_code == 200
    assert route.called
    # Il client si identifica sempre con lo User-Agent del progetto.
    assert "OpenNewsBot" in route.calls[0].request.headers["User-Agent"]


def test_host_docker_internal_ammesso() -> None:
    """Ollama sul computer host (Docker Desktop): l'alias interno è locale."""
    assert host_allowed("host.docker.internal")
    assert host_allowed("gateway.docker.internal")
    assert not host_allowed("host.docker.internal.evil.com")


def test_client_senza_proxy_forza_ipv4_e_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Senza proxy: transport con retry di connessione e socket IPv4
    (httpx non ha l'happy-eyeballs; vedi Settings.http_ipv4_only)."""
    for k in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy",
              "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(k, raising=False)
    client = build_client()
    assert isinstance(client._transport, httpx.AsyncHTTPTransport)
    assert client._transport._pool._retries == 1
    assert client._transport._pool._local_address == "0.0.0.0"


def test_client_con_proxy_resta_proxy_aware(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Con un proxy configurato non montiamo il transport custom: httpx
    deve continuare a instradare attraverso il proxy."""
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.test:8080")
    client = build_client()
    assert client._mounts  # proxy montato da httpx via trust_env

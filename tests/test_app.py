"""Fase 0: l'app parte, l'healthcheck risponde, la homepage è servita."""

from httpx import AsyncClient


async def test_healthz(client: AsyncClient) -> None:
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"


async def test_homepage_vuota(client: AsyncClient) -> None:
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "OPEN NEWS" in resp.text
    assert "Prima edizione in preparazione" in resp.text
    # Il masthead dichiara sempre la versione del metodo.
    assert "Metodo v." in resp.text


async def test_static_css(client: AsyncClient) -> None:
    resp = await client.get("/static/css/main.css")
    assert resp.status_code == 200
    assert "--carta" in resp.text

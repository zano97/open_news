"""Fase 1: rispetto di robots.txt con cache."""

import httpx
import respx

from core.ingest.robots import RobotsCache
from core.net import build_client

ROBOTS = """
User-agent: *
Disallow: /privato/
"""


@respx.mock
async def test_disallow_rispettato() -> None:
    respx.get("https://fonte.test/robots.txt").mock(
        return_value=httpx.Response(200, text=ROBOTS)
    )
    async with build_client() as client:
        robots = RobotsCache(client)
        assert not await robots.can_fetch("https://fonte.test/privato/articolo")
        assert await robots.can_fetch("https://fonte.test/pubblico/articolo")


@respx.mock
async def test_robots_assente_consente() -> None:
    respx.get("https://fonte.test/robots.txt").mock(return_value=httpx.Response(404))
    async with build_client() as client:
        robots = RobotsCache(client)
        assert await robots.can_fetch("https://fonte.test/qualsiasi")


@respx.mock
async def test_cache_una_sola_richiesta() -> None:
    route = respx.get("https://fonte.test/robots.txt").mock(
        return_value=httpx.Response(200, text=ROBOTS)
    )
    async with build_client() as client:
        robots = RobotsCache(client)
        await robots.can_fetch("https://fonte.test/a")
        await robots.can_fetch("https://fonte.test/b")
        await robots.can_fetch("https://fonte.test/c")
    assert route.call_count == 1


@respx.mock
async def test_errore_di_rete_consente_ma_non_esplode() -> None:
    respx.get("https://fonte.test/robots.txt").mock(
        side_effect=httpx.ConnectError("connessione rifiutata")
    )
    async with build_client() as client:
        robots = RobotsCache(client)
        assert await robots.can_fetch("https://fonte.test/articolo")

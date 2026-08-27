"""Fase 7: pagina /metodo dal markdown, pagina /dati, export coerenti."""

from httpx import AsyncClient


async def test_pagina_metodo(client: AsyncClient) -> None:
    resp = await client.get("/metodo")
    assert resp.status_code == 200
    testo = resp.text
    assert "quattro livelli" in testo
    # Le àncore citate dall'interfaccia esistono davvero.
    assert 'id="agenda"' in testo
    assert 'id="framing"' in testo
    assert 'id="livello4"' in testo
    # I numeri della calibrazione sono dichiarati pubblicamente.
    assert "100 coppie" in testo
    assert "Krippendorff" in testo


async def test_pagina_dati(client: AsyncClient) -> None:
    resp = await client.get("/dati")
    assert resp.status_code == 200
    assert "CC BY-SA 4.0" in resp.text
    for nome in ("story.csv", "coperture.csv", "segnali.csv", "annotazioni.csv"):
        assert nome in resp.text


async def test_export_vuoti_ma_validi(client: AsyncClient) -> None:
    for endpoint in ("/dati/story.csv", "/dati/coperture.csv", "/dati/segnali.csv"):
        resp = await client.get(endpoint)
        assert resp.status_code == 200
        assert resp.text.startswith("# Open News")
        assert "CC BY-SA 4.0" in resp.text

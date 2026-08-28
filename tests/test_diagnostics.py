"""Diagnostica: registro eventi nel pannello, prova reale del generatore,
retry senza il parametro think quando il server lo rifiuta."""

import logging

import httpx
import respx
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from core.logbuffer import install, recent
from core.models import Article, Source, Story
from core.nlp import summarize
from core.nlp.summarize import summarize_story


async def _registra(client: AsyncClient, username: str) -> None:
    resp = await client.post(
        "/annota/registrati",
        data={"username": username, "password": "password-sicura"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    client.cookies.update(resp.cookies)


def test_ring_buffer_raccoglie_gli_avvisi() -> None:
    install()
    logging.getLogger("core.ingest.prova").warning("feed di prova fallito: %s", "X")
    logging.getLogger("core.ingest.prova").info("dettaglio informativo")
    messaggi = [r.message for r in recent(limit=10)]
    assert "feed di prova fallito: X" in messaggi
    # Di default il pannello mostra da WARNING in su.
    assert "dettaglio informativo" not in messaggi


async def _story_con_articoli(session: AsyncSession) -> Story:
    fonte = Source(
        slug="testata", name="Testata", domain="testata.test", country="it",
        language="it", region="italy", feed_urls=[], terms_note="",
    )
    session.add(fonte)
    await session.flush()
    story = Story(title_neutral="Titolo neutro di prova sufficientemente lungo")
    session.add(story)
    await session.flush()
    session.add(
        Article(
            source_id=fonte.id, story_id=story.id,
            url="https://testata.test/a", title="Titolo articolo",
            snippet="Estratto.", language="it",
        )
    )
    await session.flush()
    await session.refresh(story, ["articles"])
    return story


@respx.mock
async def test_retry_senza_think_se_rifiutato(
    session: AsyncSession, monkeypatch,
) -> None:
    """Alcune versioni di Ollama rifiutano `think` sui modelli che non lo
    supportano: si deve ritentare senza, non fallire."""
    monkeypatch.setattr(get_settings(), "enable_llm", True)
    story = await _story_con_articoli(session)

    route = respx.post("http://localhost:11434/api/generate")
    route.side_effect = [
        httpx.Response(400, json={"error": '"testata" does not support thinking'}),
        httpx.Response(
            200,
            json={"response": "Riassunto neutro di prova, lungo a sufficienza "
                              "per superare la soglia dei quaranta caratteri."},
        ),
    ]
    async with httpx.AsyncClient() as client:
        ok = await summarize_story(session, story, client=client)
    assert ok
    assert len(route.calls) == 2
    import json as jsonlib

    secondo = jsonlib.loads(route.calls[1].request.content)
    assert "think" not in secondo
    assert summarize.LAST_GENERATION["ok"] == "1"



@respx.mock
async def test_prova_generatore_dal_pannello(
    client: AsyncClient, monkeypatch,
) -> None:
    """Il pulsante «Prova il generatore adesso» fa una richiesta vera e
    l'esito (anche l'errore) compare nel pannello."""
    monkeypatch.setattr(get_settings(), "enable_llm", True)
    respx.get("http://localhost:11434/api/tags").mock(
        return_value=httpx.Response(200, json={"models": [{"name": "qwen2.5:7b"}]})
    )
    respx.post("http://localhost:11434/api/generate").mock(
        return_value=httpx.Response(500, text="model runner has unexpectedly stopped")
    )
    await _registra(client, "admin-diag")
    resp = await client.post(
        "/impostazioni/prova-generatore", follow_redirects=False
    )
    assert resp.status_code == 303
    pagina = await client.get("/impostazioni")
    assert "model runner has unexpectedly stopped" in pagina.text
    assert "Diagnostica" in pagina.text


def test_avviso_riavvio_dopo_aggiornamento(monkeypatch) -> None:
    """Codice su disco più nuovo del processo: il pannello deve dirlo."""
    from datetime import UTC, datetime

    from apps.api.routers.settings_panel import update_pending
    from core import logbuffer

    monkeypatch.setattr(
        logbuffer, "STARTED_AT", datetime(2000, 1, 1, tzinfo=UTC)
    )
    assert update_pending()  # i file del repo sono ovviamente più recenti

    monkeypatch.setattr(
        logbuffer, "STARTED_AT", datetime(2100, 1, 1, tzinfo=UTC)
    )
    assert not update_pending()


async def test_spegni_richiede_il_token(
    client: AsyncClient, monkeypatch,
) -> None:
    """Chiudere la finestra spegne tutto — ma solo col token del launcher;
    senza, la rotta non esiste (404) e in modalità server è inerte."""
    from apps.api.routers import health

    fermate: list[bool] = []
    monkeypatch.setattr(health, "_termina", lambda: fermate.append(True))
    monkeypatch.setenv("OPENNEWS_EMBEDDED_WORKER", "1")
    monkeypatch.setenv("OPENNEWS_SHUTDOWN_TOKEN", "token-di-prova")

    negato = await client.post("/spegni")
    assert negato.status_code == 404
    sbagliato = await client.post("/spegni", headers={"X-Opennews-Spegni": "no"})
    assert sbagliato.status_code == 404

    ok = await client.post("/spegni", headers={"X-Opennews-Spegni": "token-di-prova"})
    assert ok.status_code == 200
    import asyncio

    await asyncio.sleep(0.5)
    assert fermate == [True]

    # In modalità server (senza worker incorporato) l'endpoint è inerte.
    monkeypatch.delenv("OPENNEWS_EMBEDDED_WORKER")
    servito = await client.post("/spegni", headers={"X-Opennews-Spegni": "token-di-prova"})
    assert servito.status_code == 404


async def test_aggiorna_ora_in_sottofondo(
    client: AsyncClient, monkeypatch,
) -> None:
    """Il pulsante avvia i cicli in un task: risposta immediata, stato
    visibile via /api/aggiornamento, mai due giri sovrapposti."""
    import asyncio

    from apps.api.routers import pages

    monkeypatch.setenv("OPENNEWS_EMBEDDED_WORKER", "1")
    girati: list[str] = []

    async def finto_giro() -> None:
        girati.append("via")
        await asyncio.sleep(0.15)
        pages._aggiornamento["in_corso"] = False

    monkeypatch.setattr(pages, "_giro_di_aggiornamento", finto_giro)

    resp = await client.post("/aggiorna", follow_redirects=False)
    assert resp.status_code == 303
    stato = await client.get("/api/aggiornamento")
    assert stato.json() == {"in_corso": True}
    # Un secondo clic durante il giro non ne avvia un altro.
    await client.post("/aggiorna", follow_redirects=False)
    await asyncio.sleep(0.3)
    assert girati == ["via"]
    stato = await client.get("/api/aggiornamento")
    assert stato.json() == {"in_corso": False}


async def test_aggiorna_negato_senza_permessi(client: AsyncClient, monkeypatch) -> None:
    monkeypatch.delenv("OPENNEWS_EMBEDDED_WORKER", raising=False)
    resp = await client.post("/aggiorna", follow_redirects=False)
    assert resp.status_code == 403


def test_tracking_dei_cicli() -> None:
    """La barra si accende quando un ciclo lavora e l'esito resta in
    diagnostica."""
    import asyncio

    from core import refresh_state

    async def giro() -> None:
        async with refresh_state.tracking("prova"):
            assert refresh_state.is_running()

    asyncio.run(giro())
    assert not refresh_state.is_running()
    assert refresh_state.LAST_RUNS["prova"]["esito"] == "ok"

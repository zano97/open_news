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

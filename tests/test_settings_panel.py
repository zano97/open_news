"""Pannello /impostazioni: accesso admin, validazione, applicazione a caldo."""

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from core.models import AppSetting
from core.runtime_settings import load_overrides


async def _registra(client: AsyncClient, username: str) -> None:
    resp = await client.post(
        "/annota/registrati",
        data={"username": username, "password": "password-sicura"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    client.cookies.update(resp.cookies)


async def test_primo_utente_diventa_admin_il_secondo_no(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _registra(client, "prima")
    pagina = await client.get("/impostazioni")
    assert pagina.status_code == 200
    assert "Impostazioni" in pagina.text
    assert 'name="ollama_model"' in pagina.text  # il modello Ollama è configurabile
    assert 'name="ollama_url"' in pagina.text

    client.cookies.clear()
    await _registra(client, "seconda")
    negato = await client.get("/impostazioni")
    assert negato.status_code == 403


async def test_anonimo_non_entra(client: AsyncClient) -> None:
    resp = await client.get("/impostazioni")
    assert resp.status_code == 403


async def test_salva_e_applica(client: AsyncClient, session: AsyncSession) -> None:
    settings = get_settings()
    originali = (
        settings.ollama_model, settings.ollama_url, settings.enable_llm,
        settings.flash_min_sources,
    )
    try:
        await _registra(client, "admin")
        resp = await client.post(
            "/impostazioni",
            data={
                "enable_llm": "true",
                "ollama_model": "qwen2.5:3b",
                "ollama_url": "http://ollama:11434",
                "flash_min_sources": "4",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 303

        # Applicate a caldo sull'istanza corrente...
        assert settings.enable_llm is True
        assert settings.ollama_model == "qwen2.5:3b"
        assert settings.ollama_url == "http://ollama:11434"
        assert settings.flash_min_sources == 4

        # ...e persistite nel DB con l'autore.
        righe = {
            r.key: r for r in (await session.execute(select(AppSetting))).scalars()
        }
        assert righe["ollama_model"].value == "qwen2.5:3b"
        assert righe["ollama_model"].updated_by == "admin"

        # Un altro processo (es. il worker) le ricarica dal DB.
        settings.ollama_model = "reset-finto"
        applied = await load_overrides(session)
        assert applied >= 4
        assert settings.ollama_model == "qwen2.5:3b"

        # La pagina mostra la conferma e i valori correnti.
        pagina = await client.get("/impostazioni?salvate=1")
        assert "salvate e applicate" in pagina.text
        assert "qwen2.5:3b" in pagina.text
    finally:
        (
            settings.ollama_model, settings.ollama_url, settings.enable_llm,
            settings.flash_min_sources,
        ) = originali


async def test_validazione_respinge_valori_pericolosi(
    client: AsyncClient, session: AsyncSession
) -> None:
    settings = get_settings()
    originali = (settings.ollama_url, settings.rate_limit_seconds)
    try:
        await _registra(client, "admin2")
        resp = await client.post(
            "/impostazioni",
            data={
                # host esterno: userebbe il server come proxy — vietato
                "ollama_url": "http://api.openai.com",
                # sotto i 2 secondi: viola la cortesia di rete promessa
                "rate_limit_seconds": "0.1",
            },
        )
        assert resp.status_code == 422
        assert "allowlist" in resp.text
        assert "2" in resp.text and "60" in resp.text  # intervallo ammesso
        # Niente è cambiato né in memoria né nel DB.
        assert settings.ollama_url == originali[0]
        assert settings.rate_limit_seconds == originali[1]
        salvate = list((await session.execute(select(AppSetting))).scalars())
        chiavi = {r.key for r in salvate}
        assert "ollama_url" not in chiavi
        assert "rate_limit_seconds" not in chiavi
    finally:
        settings.ollama_url, settings.rate_limit_seconds = originali


async def test_override_corrotto_ignorato(session: AsyncSession) -> None:
    settings = get_settings()
    originale = settings.flash_min_sources
    try:
        session.add(AppSetting(key="flash_min_sources", value="non-un-numero"))
        session.add(AppSetting(key="chiave_sconosciuta", value="x"))
        await session.flush()
        await load_overrides(session)
        assert settings.flash_min_sources == originale  # mai un crash, mai spazzatura
    finally:
        settings.flash_min_sources = originale

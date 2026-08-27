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


class TestStatoLLM:
    """Il pannello diagnostica Ollama in diretta: mai un fallimento silenzioso."""

    async def test_spento_mostra_suggerimento(self, client: AsyncClient) -> None:
        await _registra(client, "admin-llm-0")
        pagina = await client.get("/impostazioni")
        assert "disattivati" in pagina.text

    async def test_ollama_giu_mostra_errore_e_comando(
        self, client: AsyncClient
    ) -> None:
        import respx as respx_mod

        settings = get_settings()
        originale = settings.enable_llm
        settings.enable_llm = True
        try:
            await _registra(client, "admin-llm-1")
            with respx_mod.mock:
                respx_mod.get("http://localhost:11434/api/tags").mock(
                    side_effect=__import__("httpx").ConnectError("connessione rifiutata")
                )
                pagina = await client.get("/impostazioni")
            assert "NON raggiungibile" in pagina.text
            assert "docker compose --profile llm up -d" in pagina.text
        finally:
            settings.enable_llm = originale

    async def test_modello_mancante_indica_il_pull(
        self, client: AsyncClient
    ) -> None:
        import httpx as httpx_mod
        import respx as respx_mod

        settings = get_settings()
        originale = settings.enable_llm
        settings.enable_llm = True
        try:
            await _registra(client, "admin-llm-2")
            with respx_mod.mock:
                respx_mod.get("http://localhost:11434/api/tags").mock(
                    return_value=httpx_mod.Response(
                        200, json={"models": [{"name": "llama3:8b"}]}
                    )
                )
                pagina = await client.get("/impostazioni")
            assert "NON è installato" in pagina.text
            assert "ollama pull qwen2.5:7b" in pagina.text
            assert "llama3:8b" in pagina.text
        finally:
            settings.enable_llm = originale

    async def test_genera_ora_produce_riassunti(
        self, client: AsyncClient, session: AsyncSession
    ) -> None:
        import httpx as httpx_mod
        import respx as respx_mod

        from core.models import Article, Source, Story, utcnow

        settings = get_settings()
        originale = settings.enable_llm
        settings.enable_llm = True
        try:
            story = Story(
                title_neutral="Evento da riassumere subito",
                first_seen=utcnow(), last_seen=utcnow(),
                article_count=2, source_count=2,
            )
            session.add(story)
            await session.flush()
            for i in range(2):
                fonte = Source(
                    slug=f"ora-{i}", name=f"Ora {i}", domain=f"ora{i}.test",
                    country="it", language="it", region="italy",
                    feed_urls=[], terms_note="",
                )
                session.add(fonte)
                await session.flush()
                session.add(
                    Article(
                        source_id=fonte.id, url=f"https://ora{i}.test/1",
                        title=f"Evento, versione {i}", language="it",
                        story_id=story.id,
                    )
                )
            await session.commit()

            await _registra(client, "admin-llm-3")
            with respx_mod.mock:
                respx_mod.post("http://localhost:11434/api/generate").mock(
                    return_value=httpx_mod.Response(
                        200,
                        json={"response": (
                            "Le testate riferiscono lo stesso evento con due "
                            "formulazioni diverse; nessuna vittima segnalata."
                        )},
                    )
                )
                resp = await client.post(
                    "/impostazioni/riassunti-prova", follow_redirects=False
                )
            assert resp.status_code == 303
            assert resp.headers["location"] == "/impostazioni?riassunti=1"
            await session.refresh(story)
            assert story.summary_neutral is not None
            assert story.summary_method == "llm"
        finally:
            settings.enable_llm = originale

    async def test_genera_ora_negato_ai_non_admin(self, client: AsyncClient) -> None:
        resp = await client.post("/impostazioni/riassunti-prova")
        assert resp.status_code == 403


async def test_url_ollama_host_docker_internal_accettato(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Chi ha Ollama sul computer (fuori dai container) usa l'alias Docker."""
    settings = get_settings()
    originale = settings.ollama_url
    try:
        await _registra(client, "admin-host")
        resp = await client.post(
            "/impostazioni",
            data={"ollama_url": "http://host.docker.internal:11434"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert settings.ollama_url == "http://host.docker.internal:11434"
    finally:
        settings.ollama_url = originale


async def test_altro_processo_vede_le_impostazioni_salvate(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Regressione multi-worker: un salvataggio fatto da un processo deve
    valere anche per gli altri, che ricaricano gli override a ogni richiesta."""
    import httpx as httpx_mod
    import respx as respx_mod

    from core.models import Article, Source, Story, utcnow

    settings = get_settings()
    originale = settings.enable_llm
    try:
        # Una story con due testate, come nella pagina reale.
        story = Story(
            title_neutral="Evento multi-processo", first_seen=utcnow(),
            last_seen=utcnow(), article_count=2, source_count=2,
        )
        session.add(story)
        await session.flush()
        for i in range(2):
            fonte = Source(
                slug=f"mp-{i}", name=f"MP {i}", domain=f"mp{i}.test",
                country="it", language="it", region="italy",
                feed_urls=[], terms_note="",
            )
            session.add(fonte)
            await session.flush()
            session.add(
                Article(
                    source_id=fonte.id, url=f"https://mp{i}.test/1",
                    title=f"Evento, versione {i}", language="it",
                    story_id=story.id,
                )
            )
        await session.commit()

        # "Processo A": l'admin attiva i riassunti dal pannello.
        await _registra(client, "admin-mp")
        resp = await client.post(
            "/impostazioni", data={"enable_llm": "true"}, follow_redirects=False
        )
        assert resp.status_code == 303

        # "Processo B": memoria vecchia (enable_llm spento)...
        settings.enable_llm = False

        # ...ma la pagina della story ricarica gli override: pulsante presente.
        pagina = await client.get(f"/storia/{story.id}")
        assert "data-riassunto-btn" in pagina.text

        # ...e anche la generazione funziona dal "processo" con memoria vecchia.
        settings.enable_llm = False
        flusso = (
            '{"response": "Riassunto di prova sufficientemente lungo '
            'per il salvataggio.", "done": true}\n'
        )
        with respx_mod.mock:
            respx_mod.post(
                f"{settings.ollama_url.rstrip('/')}/api/generate"
            ).mock(return_value=httpx_mod.Response(200, text=flusso))
            gen = await client.post(f"/storia/{story.id}/riassunto")
        assert gen.status_code == 200
        await session.refresh(story)
        assert story.summary_neutral is not None
    finally:
        settings.enable_llm = originale

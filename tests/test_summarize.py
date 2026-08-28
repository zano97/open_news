"""Riassunto neutro con LLM locale: marcato, con provenance, mai obbligatorio."""

import httpx
import pytest
import respx
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core import provenance
from core.config import get_settings
from core.models import Article, Source, Story, utcnow
from core.nlp.summarize import build_prompt, summarize_story

RIASSUNTO = (
    "Il consiglio dei ministri ha approvato la riforma delle pensioni dopo "
    "mesi di trattative con i sindacati. La misura entrerà in vigore da "
    "gennaio e riguarda i lavoratori del settore privato."
)


@pytest.fixture
def llm_attivo() -> None:
    settings = get_settings()
    originale = settings.enable_llm
    settings.enable_llm = True
    yield
    settings.enable_llm = originale


async def _story_multi_fonte(session: AsyncSession) -> Story:
    story = Story(
        title_neutral="Pensioni, il governo approva la riforma",
        first_seen=utcnow(), last_seen=utcnow(),
        article_count=2, source_count=2,
    )
    session.add(story)
    await session.flush()
    for i in range(2):
        fonte = Source(
            slug=f"sum-{i}", name=f"Fonte {i}", domain=f"sum{i}.test",
            country="it", language="it", region="italy", feed_urls=[], terms_note="",
        )
        session.add(fonte)
        await session.flush()
        session.add(
            Article(
                source_id=fonte.id,
                url=f"https://sum{i}.test/pensioni",
                title=f"Pensioni, via libera alla riforma (versione {i})",
                snippet="Accordo trovato dopo mesi di trattative.",
                language="it",
                story_id=story.id,
            )
        )
    await session.flush()
    await session.refresh(story)
    return story


def test_prompt_include_articoli_e_lingua_del_lettore() -> None:
    """Il prompt porta titoli, estratti e testo integrale (troncato, uso
    interno) e chiede la lingua dell'interfaccia; il testo non è mai
    illimitato."""
    # build_prompt legge story.articles: basta un oggetto compatibile.
    class FonteFinta:
        name = "Testata X"

    class ArticoloFinto:
        source = FonteFinta()
        title = "Titolo pubblico"
        snippet = "Estratto pubblico."
        language = "it"
        full_text = "Corpo dell'articolo. " * 300  # ben oltre il limite

    class StoryFinta:
        def __init__(self) -> None:
            self.articles = [ArticoloFinto()]

    from core.nlp.summarize import MAX_CHARS_PER_ARTICLE

    prompt = build_prompt(StoryFinta(), "en")  # type: ignore[arg-type]
    assert "Titolo pubblico" in prompt
    assert "Estratto pubblico." in prompt
    assert "Corpo dell'articolo." in prompt  # il testo ENTRA nel prompt…
    # …ma troncato al limite per articolo.
    corpo = prompt.split("Testo: ", 1)[1]
    assert len(corpo) <= MAX_CHARS_PER_ARTICLE + 10
    assert "ENGLISH" in prompt  # la lingua dell'output è quella del lettore
    prompt_de = build_prompt(StoryFinta(), "de")  # type: ignore[arg-type]
    assert "DEUTSCH" in prompt_de


@respx.mock
async def test_riassunto_generato_e_marcato(
    session: AsyncSession, llm_attivo: None
) -> None:
    story = await _story_multi_fonte(session)
    route = respx.post("http://localhost:11434/api/generate").mock(
        return_value=httpx.Response(200, json={"response": RIASSUNTO})
    )
    async with httpx.AsyncClient() as client:
        ok = await summarize_story(session, story, client=client)
    assert ok
    assert route.called
    assert story.summary_neutral == RIASSUNTO
    assert story.summary_method == "llm"  # sempre marcato

    prova = await provenance.for_entity(session, "story", story.id)
    riga = next(p for p in prova if p.field == "summary")
    assert riga.method == "ollama-summary-v2"
    assert "uso interno, mai mostrato" in str(riga.inputs)


async def test_flag_spento_non_fa_nulla(session: AsyncSession) -> None:
    story = await _story_multi_fonte(session)
    async with httpx.AsyncClient() as client:
        ok = await summarize_story(session, story, client=client)
    assert not ok
    assert story.summary_neutral is None


@respx.mock
async def test_errore_ollama_gestito(
    session: AsyncSession, llm_attivo: None
) -> None:
    story = await _story_multi_fonte(session)
    respx.post("http://localhost:11434/api/generate").mock(
        side_effect=httpx.ConnectError("ollama non attivo")
    )
    async with httpx.AsyncClient() as client:
        ok = await summarize_story(session, story, client=client)
    assert not ok
    assert story.summary_neutral is None


async def test_pagina_storia_mostra_riassunto_marcato(
    client: AsyncClient, session: AsyncSession
) -> None:
    story = await _story_multi_fonte(session)
    story.summary_neutral = RIASSUNTO
    story.summary_method = "llm"
    await session.commit()

    resp = await client.get(f"/storia/{story.id}")
    assert resp.status_code == 200
    testo = resp.text
    assert "Il fatto in breve" in testo
    assert "riforma delle pensioni" in testo
    # La marcatura "automatico" è sempre accanto al riassunto.
    assert "automaticamente" in testo
    assert "fanno fede gli articoli originali" in testo


class TestRiassuntoSuRichiesta:
    """Il riassunto si genera SOLO quando il lettore lo chiede, in streaming."""

    async def test_streaming_genera_salva_e_marca(
        self, client: AsyncClient, session: AsyncSession, llm_attivo: None
    ) -> None:
        story = await _story_multi_fonte(session)
        await session.commit()
        flusso = (
            '{"response": "Le testate riferiscono lo stesso evento: "}\n'
            '{"response": "accordo raggiunto dopo mesi di trattative, '
            'nessuna vittima segnalata.", "done": true}\n'
        )
        with respx.mock:
            respx.post("http://localhost:11434/api/generate").mock(
                return_value=httpx.Response(200, text=flusso)
            )
            resp = await client.post(f"/storia/{story.id}/riassunto")
        assert resp.status_code == 200
        assert "accordo raggiunto" in resp.text

        await session.refresh(story)
        assert story.summary_neutral is not None
        assert story.summary_method == "llm"
        prova = await provenance.for_entity(session, "story", story.id)
        riga = next(p for p in prova if p.field == "summary")
        assert riga.inputs["trigger"] == "richiesta del lettore"

        # Seconda richiesta: torna il salvato, senza rigenerare.
        with respx.mock:  # nessuna rotta: una chiamata a Ollama fallirebbe
            di_nuovo = await client.post(f"/storia/{story.id}/riassunto")
        assert di_nuovo.status_code == 200
        assert di_nuovo.text == story.summary_neutral

    async def test_generatore_spento_503(
        self, client: AsyncClient, session: AsyncSession
    ) -> None:
        story = await _story_multi_fonte(session)
        await session.commit()
        resp = await client.post(f"/storia/{story.id}/riassunto")
        assert resp.status_code == 503

    async def test_story_inesistente_404(
        self, client: AsyncClient, llm_attivo: None
    ) -> None:
        resp = await client.post("/storia/99999/riassunto")
        assert resp.status_code == 404

    async def test_pagina_mostra_il_pulsante_quando_attivo(
        self, client: AsyncClient, session: AsyncSession, llm_attivo: None
    ) -> None:
        story = await _story_multi_fonte(session)
        await session.commit()
        pagina = await client.get(f"/storia/{story.id}")
        assert "data-riassunto-btn" in pagina.text
        assert "Genera «Il fatto in breve»" in pagina.text

    async def test_pagina_senza_pulsante_quando_spento(
        self, client: AsyncClient, session: AsyncSession
    ) -> None:
        story = await _story_multi_fonte(session)
        await session.commit()
        pagina = await client.get(f"/storia/{story.id}")
        assert "data-riassunto-btn" not in pagina.text


def test_think_filter_nasconde_il_ragionamento() -> None:
    """I modelli "pensanti" premettono <think>…</think>: mai mostrarlo,
    anche quando i tag arrivano spezzati su più pezzi di flusso."""
    from core.nlp.summarize import ThinkFilter, strip_think

    filtro = ThinkFilter()
    visibile = "".join(
        filtro.feed(pezzo)
        for pezzo in ["<th", "ink>ragiono ", "molto</think>", "\nIl fatto: ", "accordo."]
    )
    assert visibile == "Il fatto: accordo."

    # Senza blocco think: tutto passa, anche se inizia con "<" ambiguo.
    normale = ThinkFilter()
    assert "".join(normale.feed(p) for p in ["<b>Tit", "olo</b> resto"]) == "<b>Titolo</b> resto"

    assert strip_think("<think>bla bla</think>\nRiassunto vero.") == "Riassunto vero."
    assert strip_think("Riassunto senza ragionamento.") == "Riassunto senza ragionamento."

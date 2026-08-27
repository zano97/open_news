"""Riassunto neutro delle story con LLM locale (Ollama), sempre marcato.

Perché esiste: il testo integrale degli articoli non può essere mostrato
(è delle testate; vedi docs/LEGAL.md), ma il lettore merita "il fatto in
breve" senza lasciare la pagina. Il riassunto:

- è generato IN LOCALE da un modello aperto via Ollama (nessun servizio a
  pagamento, nessun dato che lascia la macchina);
- usa SOLO titoli ed estratti già pubblici nei feed, mai il testo integrale;
- è sempre marcato "riassunto automatico" con provenance (modello, versione);
- non è mai il giudice del bias: descrive l'evento, non valuta le testate.

Feature-flag: ENABLE_LLM=false di default; il sistema funziona senza.
"""

import logging

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from core.models import Story
from core.provenance import record

log = logging.getLogger(__name__)

METHOD_NAME = "ollama-summary-v1"
MAX_INPUT_ARTICLES = 8

_PROMPTS = {
    "it": (
        "Sei un'agenzia di stampa neutrale. Scrivi un riassunto di 3-4 frasi "
        "dell'evento descritto dai titoli e dagli estratti seguenti, presi da "
        "testate diverse. Regole: usa SOLO le informazioni presenti qui sotto; "
        "non aggiungere fatti, numeri o nomi non presenti; nessuna opinione, "
        "nessun aggettivo valutativo; se le testate si contraddicono, dillo. "
        "Rispondi solo con il riassunto, in italiano.\n\n{materiale}"
    ),
    "en": (
        "You are a neutral wire service. Write a 3-4 sentence summary of the "
        "event described by the following headlines and excerpts from "
        "different outlets. Rules: use ONLY the information below; do not add "
        "facts, numbers or names not present; no opinions, no evaluative "
        "adjectives; if outlets contradict each other, say so. Reply with the "
        "summary only, in English.\n\n{materiale}"
    ),
}


def build_prompt(story: Story) -> str:
    """Prompt dal materiale già pubblico (titoli+estratti), mai testo integrale."""
    articles = story.articles[:MAX_INPUT_ARTICLES]
    languages = [a.language for a in articles if a.language]
    dominant = max(set(languages), key=languages.count) if languages else "en"
    template = _PROMPTS.get(dominant, _PROMPTS["en"])
    lines = []
    for a in articles:
        line = f"- [{a.source.name}] {a.title}"
        if a.snippet:
            line += f" — {a.snippet}"
        lines.append(line)
    return template.format(materiale="\n".join(lines))


async def summarize_story(
    session: AsyncSession, story: Story, *, client: httpx.AsyncClient
) -> bool:
    """Genera e salva il riassunto neutro. False se il flag è spento o fallisce."""
    settings = get_settings()
    if not settings.enable_llm:
        return False
    if not story.articles:
        return False
    try:
        resp = await client.post(
            f"{settings.ollama_url.rstrip('/')}/api/generate",
            json={
                "model": settings.ollama_model,
                "prompt": build_prompt(story),
                "stream": False,
                "options": {"temperature": 0.2, "num_predict": 260},
            },
            timeout=120,
        )
        resp.raise_for_status()
        text = str(resp.json().get("response", "")).strip()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("riassunto story %d fallito: %s", story.id, exc)
        return False
    if len(text) < 40:
        log.info("riassunto story %d troppo corto, scartato", story.id)
        return False

    story.summary_neutral = text
    story.summary_method = "llm"
    await record(
        session,
        entity_type="story",
        entity_id=story.id,
        field="summary",
        method=METHOD_NAME,
        inputs={
            "model": settings.ollama_model,
            "n_articles": min(len(story.articles), MAX_INPUT_ARTICLES),
            "input": "titoli+estratti (mai testo integrale)",
        },
    )
    await session.flush()
    return True

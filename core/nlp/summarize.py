"""Riassunto neutro delle story con LLM locale (Ollama), sempre marcato.

Perché esiste: il testo integrale degli articoli non può essere mostrato
(è delle testate; vedi docs/LEGAL.md), ma il lettore merita "il fatto in
breve" senza lasciare la pagina. Il riassunto:

- è generato IN LOCALE da un modello aperto via Ollama (nessun servizio a
  pagamento, nessun dato che lascia la macchina);
- legge titoli, estratti e il testo integrale scaricato per uso interno,
  ma l'output è SEMPRE in parole proprie: mai frasi degli articoli, mai il
  testo integrale mostrato (docs/LEGAL.md);
- è nella lingua dell'interfaccia del lettore, salvato per lingua;
- è sempre marcato "riassunto automatico" con provenance (modello, versione);
- non è mai il giudice del bias: descrive l'evento, non valuta le testate.

Feature-flag: ENABLE_LLM=false di default; il sistema funziona senza.
"""

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from core.models import Story, utcnow
from core.provenance import record

log = logging.getLogger(__name__)

METHOD_NAME = "ollama-summary-v2"
MAX_INPUT_ARTICLES = 12
# Budget di token della risposta: il riassunto è di 120-180 parole e i
# modelli "pensanti" possono comunque spenderne una parte in ragionamento.
NUM_PREDICT = 700


class ThinkFilter:
    """Toglie da un flusso di testo il blocco <think>…</think> iniziale.

    I modelli "pensanti" (qwen3, deepseek-r1, …) premettono il ragionamento
    alla risposta; chiediamo `think: false` ma alcune build lo emettono nel
    testo comunque. Il ragionamento non va mai mostrato né salvato.
    """

    _PREFIX = "<think>"
    _SUFFIX = "</think>"

    def __init__(self) -> None:
        self._buffer = ""
        self._decided = False
        self._hiding = False
        self._trim_lead = False

    def feed(self, chunk: str) -> str:
        """Restituisce la parte visibile di questo pezzo di flusso."""
        if self._decided and not self._hiding:
            if self._trim_lead:
                chunk = chunk.lstrip("\n")
                if chunk:
                    self._trim_lead = False
            return chunk
        self._buffer += chunk
        if not self._decided:
            stripped = self._buffer.lstrip()
            if not stripped:
                return ""
            if stripped.startswith(self._PREFIX):
                self._decided = True
                self._hiding = True
            elif self._PREFIX.startswith(stripped[: len(self._PREFIX)]):
                return ""  # troppo presto per decidere ("<thi…")
            else:
                self._decided = True
                out, self._buffer = self._buffer, ""
                return out
        end = self._buffer.find(self._SUFFIX)
        if end == -1:
            return ""
        out = self._buffer[end + len(self._SUFFIX) :].lstrip("\n")
        self._buffer = ""
        self._hiding = False
        self._trim_lead = not out  # il ritorno a capo dopo </think> non si mostra
        return out


def strip_think(text: str) -> str:
    """Versione non-streaming del filtro, per le risposte intere."""
    filtro = ThinkFilter()
    return filtro.feed(text).strip()


def generation_payload(
    prompt: str, *, stream: bool, include_think: bool = True
) -> dict[str, object]:
    """Corpo della richiesta a /api/generate di Ollama.

    `think: false` spegne il ragionamento dei modelli "pensanti" (qwen3,
    deepseek-r1); alcune versioni di Ollama però RIFIUTANO il parametro sui
    modelli che non lo supportano: chi chiama ritenta con
    `include_think=False` quando `think_rejected` lo segnala.
    """
    settings = get_settings()
    payload: dict[str, object] = {
        "model": settings.ollama_model,
        "prompt": prompt,
        "stream": stream,
        "options": {"temperature": 0.2, "num_predict": NUM_PREDICT},
    }
    if include_think:
        payload["think"] = False
    return payload


def think_rejected(status_code: int, body: str) -> bool:
    """Vero se il server ha rifiutato la richiesta per il parametro think."""
    return status_code == 400 and "think" in body.lower()


# Esito dell'ultima generazione (di prova o su richiesta del lettore):
# mostrato nel pannello /impostazioni, così un fallimento non è mai muto.
LAST_GENERATION: dict[str, str] = {}


def record_generation(esito: str, *, ok: bool) -> None:
    LAST_GENERATION["quando"] = utcnow().strftime("%Y-%m-%d %H:%M UTC")
    LAST_GENERATION["esito"] = esito
    LAST_GENERATION["ok"] = "1" if ok else ""

_PROMPTS = {
    "it": (
        "Sei un'agenzia di stampa neutrale. Qui sotto trovi gli articoli di "
        "più testate sullo stesso evento (titolo, estratto e, quando "
        "disponibile, il testo). Scrivi in ITALIANO un riassunto di 120-180 "
        "parole con le informazioni fondamentali: cosa è successo, chi è "
        "coinvolto, dove e quando, numeri e conseguenze riportati. Regole: "
        "PAROLE TUE, mai frasi copiate dagli articoli; usa SOLO le "
        "informazioni presenti qui sotto; non aggiungere fatti, numeri o "
        "nomi non presenti; nessuna opinione, nessun aggettivo valutativo; "
        "se le testate riportano versioni diverse, dillo. Rispondi solo con "
        "il riassunto.\n\n{materiale}"
    ),
    "en": (
        "You are a neutral wire service. Below are articles from several "
        "outlets about the same event (headline, excerpt and, when "
        "available, the text). Write in ENGLISH a 120-180 word summary with "
        "the essential information: what happened, who is involved, where "
        "and when, reported figures and consequences. Rules: YOUR OWN "
        "WORDS, never sentences copied from the articles; use ONLY the "
        "information below; do not add facts, numbers or names not present; "
        "no opinions, no evaluative adjectives; if outlets report different "
        "versions, say so. Reply with the summary only.\n\n{materiale}"
    ),
    "fr": (
        "Vous êtes une agence de presse neutre. Ci-dessous, des articles de "
        "plusieurs médias sur le même événement (titre, extrait et, si "
        "disponible, le texte). Rédigez en FRANÇAIS un résumé de 120 à 180 "
        "mots avec les informations essentielles : ce qui s'est passé, qui "
        "est impliqué, où et quand, les chiffres et conséquences rapportés. "
        "Règles : VOS PROPRES MOTS, jamais de phrases copiées ; utilisez "
        "UNIQUEMENT les informations ci-dessous ; n'ajoutez ni faits, ni "
        "chiffres, ni noms absents ; aucune opinion, aucun adjectif "
        "évaluatif ; si les médias divergent, dites-le. Répondez uniquement "
        "par le résumé.\n\n{materiale}"
    ),
    "de": (
        "Sie sind eine neutrale Nachrichtenagentur. Unten stehen Artikel "
        "mehrerer Medien zum selben Ereignis (Titel, Auszug und, falls "
        "verfügbar, der Text). Schreiben Sie auf DEUTSCH eine "
        "Zusammenfassung von 120-180 Wörtern mit den wesentlichen "
        "Informationen: was geschah, wer beteiligt ist, wo und wann, "
        "berichtete Zahlen und Folgen. Regeln: EIGENE WORTE, keine "
        "kopierten Sätze; NUR die Informationen unten verwenden; keine "
        "Fakten, Zahlen oder Namen hinzufügen, die nicht vorkommen; keine "
        "Meinungen, keine wertenden Adjektive; wenn die Medien "
        "unterschiedlich berichten, sagen Sie es. Antworten Sie nur mit der "
        "Zusammenfassung.\n\n{materiale}"
    ),
    "es": (
        "Eres una agencia de noticias neutral. Abajo hay artículos de "
        "varios medios sobre el mismo hecho (titular, extracto y, cuando "
        "está disponible, el texto). Escribe en ESPAÑOL un resumen de "
        "120-180 palabras con la información esencial: qué ocurrió, "
        "quiénes participan, dónde y cuándo, cifras y consecuencias "
        "reportadas. Reglas: TUS PROPIAS PALABRAS, nunca frases copiadas; "
        "usa SOLO la información de abajo; no añadas hechos, cifras o "
        "nombres ausentes; sin opiniones ni adjetivos valorativos; si los "
        "medios difieren, dilo. Responde solo con el resumen.\n\n{materiale}"
    ),
}

# Quanto testo integrale per articolo entra nel prompt (uso INTERNO: serve
# al riassunto in parole proprie, non viene mai mostrato né citato).
MAX_CHARS_PER_ARTICLE = 1200


def select_input_articles(story: Story) -> list[Any]:
    """Gli articoli che alimentano il riassunto: uno per testata, fino a
    MAX_INPUT_ARTICLES, preferendo chi ha il testo integrale scaricato
    (più sostanza) e poi l'ordine di pubblicazione. Niente ordine
    arbitrario: la scelta è dichiarata e riproducibile."""
    per_source: dict[int, Any] = {}
    for a in story.articles:
        gia = per_source.get(a.source_id)
        if gia is None or (a.full_text and not gia.full_text):
            per_source[a.source_id] = a
    scelti = sorted(
        per_source.values(),
        key=lambda a: (
            0 if a.full_text else 1,
            a.published_at or a.fetched_at or utcnow(),
        ),
    )
    return scelti[:MAX_INPUT_ARTICLES]


def input_stats(story: Story) -> tuple[int, int, int]:
    """(articoli usati, testate, di cui con testo integrale) — mostrati al
    lettore accanto al riassunto: la base del testo è verificabile."""
    scelti = select_input_articles(story)
    con_testo = sum(1 for a in scelti if a.full_text)
    return len(scelti), len({a.source_id for a in scelti}), con_testo


def build_prompt(story: Story, locale: str = "it") -> str:
    """Prompt dagli articoli della story, nella lingua dell'interfaccia.

    Include titolo, estratto e — quando è stato scaricato — il testo
    integrale (troncato): è l'uso interno previsto da docs/LEGAL.md, il
    riassunto che ne esce è sempre in parole proprie e marcato automatico.
    """
    articles = select_input_articles(story)
    template = _PROMPTS.get(locale, _PROMPTS["en"])
    lines = []
    for a in articles:
        line = f"- [{a.source.name}] {a.title}"
        if a.snippet:
            line += f" — {a.snippet}"
        if a.full_text:
            line += f"\n  Testo: {a.full_text[:MAX_CHARS_PER_ARTICLE]}"
        lines.append(line)
    return template.format(materiale="\n".join(lines))


async def summarize_story(
    session: AsyncSession, story: Story, *, client: httpx.AsyncClient,
    locale: str = "it",
) -> bool:
    """Genera e salva il riassunto neutro nella lingua indicata."""
    settings = get_settings()
    if not settings.enable_llm:
        return False
    if not story.articles:
        return False
    url = f"{settings.ollama_url.rstrip('/')}/api/generate"
    prompt = build_prompt(story, locale)
    try:
        resp = await client.post(
            url, json=generation_payload(prompt, stream=False), timeout=180
        )
        if think_rejected(resp.status_code, resp.text):
            # Il server non accetta il parametro think: si riprova senza.
            resp = await client.post(
                url,
                json=generation_payload(prompt, stream=False, include_think=False),
                timeout=180,
            )
        resp.raise_for_status()
        text = strip_think(str(resp.json().get("response", "")))
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("riassunto story %d fallito: %s", story.id, exc)
        record_generation(f"{exc.__class__.__name__}: {exc}", ok=False)
        return False
    if len(text) < 40:
        log.info("riassunto story %d troppo corto, scartato", story.id)
        record_generation(
            f"risposta inutilizzabile ({len(text)} caratteri)", ok=False
        )
        return False
    record_generation(f"riassunto salvato per la story {story.id}", ok=True)

    riassunti = dict(story.summaries or {})
    riassunti[locale] = text
    story.summaries = riassunti
    if not story.summary_neutral:
        story.summary_neutral = text  # compatibilità ed export /dati
    story.summary_method = "llm"
    await record(
        session,
        entity_type="story",
        entity_id=story.id,
        field="summary",
        method=METHOD_NAME,
        inputs={
            "model": settings.ollama_model,
            "n_articles": input_stats(story)[0],
            "n_full_text": input_stats(story)[2],
            "locale": locale,
            "input": "titoli+estratti+testo integrale (uso interno, mai mostrato)",
        },
    )
    await session.flush()
    return True


async def stories_needing_summary(
    session: AsyncSession, limit: int = 10, *, window_hours: int = 48
) -> list[Story]:
    """Story recenti multi-fonte ancora senza riassunto (le più coperte prima)."""
    since = utcnow() - timedelta(hours=window_hours)
    rows = (
        await session.execute(
            select(Story)
            .where(
                Story.summary_neutral.is_(None),
                Story.source_count >= 2,
                Story.last_seen >= since,
            )
            .order_by(Story.source_count.desc())
            .limit(limit)
        )
    ).scalars()
    return list(rows)


@dataclass
class OllamaStatus:
    """Diagnosi in diretta per il pannello admin: mai un fallimento silenzioso."""

    enabled: bool
    url: str
    model: str
    reachable: bool = False
    model_present: bool = False
    models: list[str] = field(default_factory=list)
    error: str | None = None


def _model_matches(installed: str, wanted: str) -> bool:
    if installed == wanted:
        return True
    # "qwen2.5" combacia con "qwen2.5:latest" (comportamento di Ollama).
    return ":" not in wanted and installed.split(":")[0] == wanted


async def check_ollama(client: httpx.AsyncClient) -> OllamaStatus:
    """Interroga /api/tags di Ollama: raggiungibilità e modelli installati."""
    settings = get_settings()
    status = OllamaStatus(
        enabled=settings.enable_llm,
        url=settings.ollama_url,
        model=settings.ollama_model,
    )
    if not status.enabled:
        return status
    try:
        resp = await client.get(
            f"{settings.ollama_url.rstrip('/')}/api/tags", timeout=5
        )
        resp.raise_for_status()
        status.models = [
            str(m.get("name", "")) for m in resp.json().get("models", [])
        ]
    except (httpx.HTTPError, ValueError) as exc:
        status.error = f"{exc.__class__.__name__}: {exc}"
        return status
    status.reachable = True
    status.model_present = any(
        _model_matches(name, status.model) for name in status.models
    )
    return status

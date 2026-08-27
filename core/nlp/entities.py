"""Entità delle story: estrazione euristica dai titoli + collegamento Wikidata.

Metodo "entities-heuristic-v1": sequenze di parole capitalizzate che compaiono
in almeno due titoli del cluster (o due volte nello stesso). Il collegamento a
Wikidata (QID) avviene in un secondo momento, via API pubblica con cache: se
manca, l'entità resta mostrata come "non collegata" — mai un QID indovinato.
Con l'extra [ml] (spaCy/GLiNER) la qualità sale; il metodo resta dichiarato.
"""

import logging
import re
from collections import Counter

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import Story
from core.nlp.entity_link import search_entity
from core.provenance import record

log = logging.getLogger(__name__)

METHOD_NAME = "entities-heuristic-v1"

_ENTITY_RE = re.compile(
    r"(?<![.!?]\s)(?<!^)\b([A-ZÀ-Þ][\wà-þ'’-]+(?:\s+[A-ZÀ-Þ][\wà-þ'’-]+){0,3})"
)

# Parole che da sole non sono entità (inizi frase frequenti, giorni, mesi...).
_ENTITY_STOP = frozenset(
    {
        "il", "la", "lo", "le", "gli", "un", "una", "the", "a", "an", "der",
        "die", "das", "les", "el", "los", "las", "dopo", "prima", "oggi",
        "domani", "ieri", "ecco", "perché", "come", "quando", "nuovo", "nuova",
    }
)


def extract_entities(titles: list[str]) -> list[dict[str, str | None]]:
    """Entità candidate dai titoli: capitalizzate, ricorrenti, senza QID."""
    counts: Counter[str] = Counter()
    for title in titles:
        seen_in_title: set[str] = set()
        for match in _ENTITY_RE.finditer(title):
            candidate = match.group(1).strip()
            words = candidate.split()
            if words and words[0].lower() in _ENTITY_STOP:
                words = words[1:]
            if not words:
                continue
            candidate = " ".join(words)
            if len(candidate) < 3 or candidate.lower() in _ENTITY_STOP:
                continue
            if candidate not in seen_in_title:
                counts[candidate] += 1
                seen_in_title.add(candidate)
    threshold = 2 if len(titles) > 1 else 1
    return [
        {"label": label, "qid": None, "type": None}
        for label, n in counts.most_common(8)
        if n >= threshold
    ]


async def assign_story_entities(session: AsyncSession, story: Story) -> int:
    titles = [a.title for a in story.articles] or [story.title_neutral]
    entities = extract_entities(titles)
    # Conserva i QID già collegati per le etichette che restano.
    known_qids = {
        e.get("label"): e.get("qid")
        for e in (story.entities or [])
        if e.get("qid")
    }
    for entity in entities:
        if entity["label"] in known_qids:
            entity["qid"] = known_qids[entity["label"]]
    story.entities = entities
    await record(
        session,
        entity_type="story",
        entity_id=story.id,
        field="entities",
        method=METHOD_NAME,
        inputs={"n_titles": len(titles)},
    )
    return len(entities)


async def link_entities_wikidata(
    session: AsyncSession,
    client: httpx.AsyncClient,
    *,
    limit: int = 10,
) -> int:
    """Collega a Wikidata le entità senza QID delle story più recenti.

    Best-effort: se la rete non c'è, le entità restano "non collegate".
    Il QID viene assegnato solo se la ricerca ha un candidato univoco in testa.
    """
    stories = (
        (
            await session.execute(
                select(Story)
                .where(Story.entities != [])
                .order_by(Story.last_seen.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    linked = 0
    for story in stories:
        entities = list(story.entities or [])
        changed = False
        for entity in entities:
            if entity.get("qid"):
                continue
            try:
                candidates = await search_entity(client, str(entity["label"]))
            except httpx.HTTPError as exc:
                log.info("wikidata non raggiungibile (%s): rimando", exc)
                return linked
            if candidates:
                entity["qid"] = candidates[0].qid
                changed = True
                linked += 1
        if changed:
            story.entities = entities
            await record(
                session,
                entity_type="story",
                entity_id=story.id,
                field="entities_qid",
                method="wikidata-search-v1",
                source_name="Wikidata",
                source_url="https://www.wikidata.org/",
            )
    await session.flush()
    return linked

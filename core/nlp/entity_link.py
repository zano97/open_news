"""Client Wikidata minimale con cache su file: fatti societari, mai etichette.

Regola del progetto (ADR-0010): da Wikidata si leggono solo fatti verificabili
(proprietario, fondatore, editore, paese, fondazione). Qualsiasi proprietà di
orientamento politico NON viene importata; al massimo l'interfaccia può citare
"secondo Wikidata" con link all'entità. Le proposte di arricchimento passano da
scripts/enrich_wikidata.py e vengono confermate a mano via pull request.
"""

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from core.config import DATA_DIR

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
CACHE_DIR = DATA_DIR / "cache" / "wikidata"
CACHE_TTL_SECONDS = 7 * 24 * 3600.0

# Proprietà ammesse: solo fatti societari.
CLAIM_PROPERTIES = {
    "P127": "owned_by",
    "P112": "founded_by",
    "P123": "publisher",
    "P17": "country",
    "P571": "inception",
}

# Fatti ammessi sulle PERSONE proprietarie: cariche, iscrizioni, occupazioni,
# aziende possedute. Sono fatti verificabili, non etichette di orientamento:
# l'iscrizione a un partito è un fatto pubblico, l'orientamento di una testata
# resta calcolato solo dalla nostra metodologia (ADR-0010).
PERSON_PROPERTIES = {
    "P39": "position_held",
    "P102": "party",
    "P106": "occupation",
    "P108": "employer",
    "P1830": "owner_of",
}

_MAX_FACTS_PER_MEANING = 8


@dataclass(frozen=True)
class EntityCandidate:
    qid: str
    label: str
    description: str


@dataclass(frozen=True)
class ClaimFact:
    property: str  # es. P127
    meaning: str  # es. owned_by
    target_qid: str | None
    target_label: str | None


def _cache_path(key: str) -> Path:
    return CACHE_DIR / f"{key}.json"


def _cache_read(key: str) -> Any | None:
    path = _cache_path(key)
    if not path.exists():
        return None
    if time.time() - path.stat().st_mtime > CACHE_TTL_SECONDS:
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _cache_write(key: str, payload: Any) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(key).write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


async def search_entity(
    client: httpx.AsyncClient, name: str, *, language: str = "it", limit: int = 5
) -> list[EntityCandidate]:
    key = f"search_{language}_{name.lower().replace(' ', '_')[:80]}"
    payload = _cache_read(key)
    if payload is None:
        resp = await client.get(
            WIKIDATA_API,
            params={
                "action": "wbsearchentities",
                "search": name,
                "language": language,
                "format": "json",
                "limit": str(limit),
            },
        )
        resp.raise_for_status()
        payload = resp.json()
        _cache_write(key, payload)
    return [
        EntityCandidate(
            qid=item["id"],
            label=item.get("label", ""),
            description=item.get("description", ""),
        )
        for item in payload.get("search", [])
    ]


async def fetch_entity(client: httpx.AsyncClient, qid: str) -> dict[str, Any]:
    key = f"entity_{qid}"
    payload = _cache_read(key)
    if payload is None:
        resp = await client.get(
            WIKIDATA_API,
            params={
                "action": "wbgetentities",
                "ids": qid,
                "props": "claims|labels",
                "languages": "it|en",
                "format": "json",
            },
        )
        resp.raise_for_status()
        payload = resp.json()
        _cache_write(key, payload)
    entity: dict[str, Any] = payload.get("entities", {}).get(qid, {})
    return entity


def parse_company_claims(entity: dict[str, Any]) -> list[ClaimFact]:
    """Estrae solo i fatti societari ammessi dai claim di un'entità."""
    facts: list[ClaimFact] = []
    claims = entity.get("claims", {})
    for prop, meaning in CLAIM_PROPERTIES.items():
        for claim in claims.get(prop, []):
            value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
            target_qid: str | None = None
            target_label: str | None = None
            if isinstance(value, dict) and "id" in value:
                target_qid = str(value["id"])
            elif isinstance(value, dict) and "time" in value:
                target_label = str(value["time"])
            elif isinstance(value, str):
                target_label = value
            facts.append(
                ClaimFact(
                    property=prop,
                    meaning=meaning,
                    target_qid=target_qid,
                    target_label=target_label,
                )
            )
    return facts


async def resolve_labels(
    client: httpx.AsyncClient, facts: list[ClaimFact]
) -> list[ClaimFact]:
    """Sostituisce i QID target con l'etichetta leggibile (it, poi en)."""
    resolved: list[ClaimFact] = []
    for fact in facts:
        if fact.target_qid and not fact.target_label:
            entity = await fetch_entity(client, fact.target_qid)
            labels = entity.get("labels", {})
            label = (labels.get("it") or labels.get("en") or {}).get("value")
            resolved.append(
                ClaimFact(fact.property, fact.meaning, fact.target_qid, label)
            )
        else:
            resolved.append(fact)
    return resolved


def _qualifier_year(claim: dict[str, Any], prop: str) -> int | None:
    try:
        time_str = claim["qualifiers"][prop][0]["datavalue"]["value"]["time"]
        return int(str(time_str)[1:5])
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def parse_person_claims(entity: dict[str, Any]) -> list[ClaimFact]:
    """Fatti ammessi su una persona, con gli anni di inizio/fine se presenti.

    Gli anni (P580/P582) viaggiano nel campo target_label come suffisso
    "|start|end" per non cambiare la dataclass: chi consuma usa
    `fact_years()` per estrarli.
    """
    facts: list[ClaimFact] = []
    claims = entity.get("claims", {})
    for prop, meaning in PERSON_PROPERTIES.items():
        rows = claims.get(prop, [])[: _MAX_FACTS_PER_MEANING]
        for claim in rows:
            value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
            if not (isinstance(value, dict) and "id" in value):
                continue
            start = _qualifier_year(claim, "P580")
            end = _qualifier_year(claim, "P582")
            marker = f"|{start or ''}|{end or ''}" if (start or end) else ""
            facts.append(
                ClaimFact(
                    property=prop,
                    meaning=meaning,
                    target_qid=str(value["id"]),
                    target_label=marker or None,
                )
            )
    return facts


def fact_years(fact: ClaimFact) -> tuple[str | None, int | None, int | None]:
    """(etichetta, anno inizio, anno fine) da un ClaimFact risolto."""
    label = fact.target_label
    start: int | None = None
    end: int | None = None
    if label and "|" in label:
        base, s_str, e_str = label.rsplit("|", 2)
        label = base or None
        start = int(s_str) if s_str.isdigit() else None
        end = int(e_str) if e_str.isdigit() else None
    return label, start, end


async def resolve_labels_keep_years(
    client: httpx.AsyncClient, facts: list[ClaimFact]
) -> list[ClaimFact]:
    """Come resolve_labels, ma conserva il suffisso anni di parse_person_claims."""
    resolved: list[ClaimFact] = []
    for fact in facts:
        marker = ""
        label = fact.target_label
        if label and label.startswith("|"):
            marker = label
            label = None
        if fact.target_qid and label is None:
            entity = await fetch_entity(client, fact.target_qid)
            labels = entity.get("labels", {})
            nome = (labels.get("it") or labels.get("en") or {}).get("value")
            resolved.append(
                ClaimFact(
                    fact.property, fact.meaning, fact.target_qid,
                    (nome or fact.target_qid) + marker,
                )
            )
        else:
            resolved.append(fact)
    return resolved

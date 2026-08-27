"""Fase 3: client Wikidata — solo fatti societari, con cache su file."""

import httpx
import respx

from core.nlp import entity_link
from core.nlp.entity_link import (
    EntityCandidate,
    fetch_entity,
    parse_company_claims,
    resolve_labels,
    search_entity,
)

SEARCH_PAYLOAD = {
    "search": [
        {"id": "Q874175", "label": "la Repubblica", "description": "quotidiano italiano"},
        {"id": "Q123456", "label": "La Repubblica (film)", "description": "film"},
    ]
}

ENTITY_PAYLOAD = {
    "entities": {
        "Q874175": {
            "labels": {"it": {"language": "it", "value": "la Repubblica"}},
            "claims": {
                "P127": [
                    {"mainsnak": {"datavalue": {"value": {"id": "Q1257575"}}}}
                ],
                "P571": [
                    {"mainsnak": {"datavalue": {"value": {"time": "+1976-01-14T00:00:00Z"}}}}
                ],
                # Una proprietà NON ammessa (orientamento politico) viene ignorata.
                "P1387": [
                    {"mainsnak": {"datavalue": {"value": {"id": "Q49637"}}}}
                ],
            },
        },
        "Q1257575": {
            "labels": {"it": {"language": "it", "value": "GEDI Gruppo Editoriale"}},
            "claims": {},
        },
    }
}


def _no_cache(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(entity_link, "CACHE_DIR", tmp_path / "wd")


@respx.mock
async def test_search_e_cache(tmp_path, monkeypatch) -> None:
    _no_cache(tmp_path, monkeypatch)
    route = respx.get(entity_link.WIKIDATA_API).mock(
        return_value=httpx.Response(200, json=SEARCH_PAYLOAD)
    )
    async with httpx.AsyncClient() as client:
        prima = await search_entity(client, "la Repubblica")
        seconda = await search_entity(client, "la Repubblica")
    assert prima == seconda
    assert prima[0] == EntityCandidate(
        qid="Q874175", label="la Repubblica", description="quotidiano italiano"
    )
    assert route.call_count == 1  # la seconda lettura viene dalla cache su file


@respx.mock
async def test_solo_fatti_societari(tmp_path, monkeypatch) -> None:
    _no_cache(tmp_path, monkeypatch)
    respx.get(entity_link.WIKIDATA_API).mock(
        return_value=httpx.Response(200, json=ENTITY_PAYLOAD)
    )
    async with httpx.AsyncClient() as client:
        entity = await fetch_entity(client, "Q874175")
        facts = parse_company_claims(entity)
        # P1387 (orientamento politico) NON deve comparire: mai etichette da terzi.
        assert all(f.property != "P1387" for f in facts)
        meanings = {f.meaning for f in facts}
        assert "owned_by" in meanings
        assert "inception" in meanings

        resolved = await resolve_labels(client, facts)
    owned = next(f for f in resolved if f.meaning == "owned_by")
    assert owned.target_label == "GEDI Gruppo Editoriale"
    assert owned.target_qid == "Q1257575"

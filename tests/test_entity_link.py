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


PERSON_PAYLOAD = {
    "entities": {
        "Q999001": {
            "labels": {"it": {"language": "it", "value": "Mario Editore"}},
            "claims": {
                "P39": [
                    {
                        "mainsnak": {"datavalue": {"value": {"id": "Q999100"}}},
                        "qualifiers": {
                            "P580": [{"datavalue": {"value": {"time": "+2008-04-29T00:00:00Z"}}}],
                        },
                    }
                ],
                "P102": [{"mainsnak": {"datavalue": {"value": {"id": "Q999200"}}}}],
                "P1830": [{"mainsnak": {"datavalue": {"value": {"id": "Q999300"}}}}],
                # Orientamento politico della persona? Non esiste come proprietà
                # qui inclusa: solo fatti (cariche, iscrizioni, aziende).
            },
        },
        "Q999100": {"labels": {"it": {"value": "deputato della Repubblica"}}, "claims": {}},
        "Q999200": {"labels": {"it": {"value": "Partito di Prova"}}, "claims": {}},
        "Q999300": {"labels": {"it": {"value": "Cliniche Riunite S.p.A."}}, "claims": {}},
    }
}


@respx.mock
async def test_fatti_persona_con_anni(tmp_path, monkeypatch) -> None:
    from core.nlp.entity_link import (
        fact_years,
        parse_person_claims,
        resolve_labels_keep_years,
    )

    _no_cache(tmp_path, monkeypatch)
    respx.get(entity_link.WIKIDATA_API).mock(
        return_value=httpx.Response(200, json=PERSON_PAYLOAD)
    )
    async with httpx.AsyncClient() as client:
        entity = await fetch_entity(client, "Q999001")
        facts = parse_person_claims(entity)
        assert {f.meaning for f in facts} == {"position_held", "party", "owner_of"}
        resolved = await resolve_labels_keep_years(client, facts)

    carica = next(f for f in resolved if f.meaning == "position_held")
    label, start, end = fact_years(carica)
    assert label == "deputato della Repubblica"
    assert start == 2008
    assert end is None
    partito = next(f for f in resolved if f.meaning == "party")
    assert fact_years(partito)[0] == "Partito di Prova"


@respx.mock
async def test_enrich_owner_scrive_details_e_provenance(
    tmp_path, monkeypatch, session
) -> None:
    from core import provenance as provenance_mod
    from core.bias.structure import enrich_owner_from_wikidata
    from core.models import Owner

    _no_cache(tmp_path, monkeypatch)
    owner = Owner(name="Mario Editore", type="persona", wikidata_qid="Q999001")
    session.add(owner)
    await session.flush()

    respx.get(entity_link.WIKIDATA_API).mock(
        return_value=httpx.Response(200, json=PERSON_PAYLOAD)
    )
    async with httpx.AsyncClient() as client:
        n = await enrich_owner_from_wikidata(session, owner, client)
    assert n == 3
    meanings = {f["meaning"] for f in owner.details["facts"]}
    assert meanings == {"position_held", "party", "owner_of"}
    carica = next(f for f in owner.details["facts"] if f["meaning"] == "position_held")
    assert carica["label"] == "deputato della Repubblica"
    assert carica["start"] == 2008

    prova = await provenance_mod.for_entity(session, "owner", owner.id)
    assert prova[0].source_name == "Wikidata"

    # Senza QID confermato: nessuna raccolta, mai un QID indovinato.
    anonimo = Owner(name="Sconosciuto", type="persona")
    session.add(anonimo)
    await session.flush()
    async with httpx.AsyncClient() as client:
        assert await enrich_owner_from_wikidata(session, anonimo, client) == 0

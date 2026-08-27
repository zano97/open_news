"""Propone arricchimenti da Wikidata per il catalogo fonti (mai automatici).

Per ogni fonte senza `wikidata_qid` cerca candidati; per ogni fonte con QID
elenca i fatti societari (owned by, founded by, publisher) "secondo Wikidata".
L'output è un rapporto testuale: le conferme passano da una modifica manuale
di data/sources.yaml / data/seeds/ownership_it.yaml via pull request, così ogni
dato resta tracciato e revisionato.

Uso: `.venv/bin/python -m scripts.enrich_wikidata`
"""

import asyncio

from core.ingest.catalog import load_catalog
from core.ingest.ratelimit import DomainRateLimiter
from core.net import build_client
from core.nlp.entity_link import (
    fetch_entity,
    parse_company_claims,
    resolve_labels,
    search_entity,
)

WIKIDATA_HOST = "www.wikidata.org"


async def main_async() -> None:
    catalog = load_catalog()
    async with build_client() as client:
        limiter = DomainRateLimiter()
        for source in catalog:
            if source.wikidata_qid:
                await limiter.wait(WIKIDATA_HOST)
                entity = await fetch_entity(client, source.wikidata_qid)
                facts = await resolve_labels(client, parse_company_claims(entity))
                print(f"\n== {source.name} ({source.wikidata_qid}) — secondo Wikidata:")
                if not facts:
                    print("   nessun fatto societario trovato")
                for fact in facts:
                    print(
                        f"   {fact.meaning}: {fact.target_label or fact.target_qid}"
                        f" [{fact.property}]"
                    )
            else:
                await limiter.wait(WIKIDATA_HOST)
                candidates = await search_entity(client, source.name)
                print(f"\n== {source.name} — QID mancante, candidati:")
                for cand in candidates:
                    print(f"   {cand.qid}: {cand.label} — {cand.description}")
                if not candidates:
                    print("   nessun candidato")
    print(
        "\nRapporto completato. Conferma i QID/fatti corretti modificando "
        "data/sources.yaml e data/seeds/ownership_it.yaml via pull request."
    )


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()

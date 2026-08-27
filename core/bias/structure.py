"""Livello 1 — Struttura: fatti verificabili su proprietà e finanziamenti.

Import idempotente dei seed curati (data/seeds/*.yaml) e lettura del profilo
completo di una fonte. Ogni riga importata porta evidenza (nome + URL) e data
di rilevamento; i valori non noti restano null e l'interfaccia mostra
"dato non disponibile" — mai una stima non dichiarata.
"""

from dataclasses import dataclass
from pathlib import Path

import httpx
import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import DATA_DIR
from core.models import BiasSignal, Owner, Ownership, PublicFunding, Source, utcnow
from core.provenance import record

OWNERSHIP_SEED_PATH = DATA_DIR / "seeds" / "ownership_it.yaml"


@dataclass
class SeedStats:
    owners: int = 0
    ownerships: int = 0
    fundings: int = 0
    skipped_missing_source: int = 0


async def load_ownership_seed(
    session: AsyncSession, path: Path = OWNERSHIP_SEED_PATH
) -> SeedStats:
    """Riversa nel DB il seed di proprietari/partecipazioni/finanziamenti."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    stats = SeedStats()

    sources = {
        s.slug: s for s in (await session.execute(select(Source))).scalars()
    }
    owners_by_name = {
        o.name: o for o in (await session.execute(select(Owner))).scalars()
    }

    for item in raw.get("owners", []):
        owner = owners_by_name.get(item["name"])
        if owner is None:
            owner = Owner(name=item["name"])
            session.add(owner)
            owners_by_name[item["name"]] = owner
            stats.owners += 1
        owner.type = item.get("type", "società")
        owner.wikidata_qid = item.get("wikidata_qid")
        owner.political_offices = item.get("political_offices") or []
        owner.source_url = item.get("evidence_url") or item.get("note")
        owner.retrieved_at = utcnow()
    await session.flush()

    for item in raw.get("ownerships", []):
        source = sources.get(item["source_slug"])
        owner = owners_by_name.get(item["owner_name"])
        if source is None or owner is None:
            stats.skipped_missing_source += 1
            continue
        row = (
            await session.execute(
                select(Ownership).where(
                    Ownership.source_id == source.id, Ownership.owner_id == owner.id
                )
            )
        ).scalar_one_or_none()
        if row is None:
            row = Ownership(source_id=source.id, owner_id=owner.id, evidence_name="")
            session.add(row)
            stats.ownerships += 1
        row.share_pct = item.get("share_pct")
        row.evidence_name = item.get("evidence_name") or "seed"
        row.evidence_url = item.get("evidence_url")
        row.note = item.get("note")
        await session.flush()
        await record(
            session,
            entity_type="source",
            entity_id=source.id,
            field=f"ownership:{owner.name}",
            method="seed-import-v1",
            inputs={"seed": str(path.name), "from_year": item.get("from_year")},
            source_name=row.evidence_name,
            source_url=row.evidence_url,
        )

    for item in raw.get("public_funding", []):
        source = sources.get(item["source_slug"])
        if source is None:
            stats.skipped_missing_source += 1
            continue
        funding = (
            await session.execute(
                select(PublicFunding).where(
                    PublicFunding.source_id == source.id,
                    PublicFunding.year == int(item["year"]),
                    PublicFunding.program == item["program"],
                )
            )
        ).scalar_one_or_none()
        if funding is None:
            funding = PublicFunding(
                source_id=source.id, year=int(item["year"]), program=item["program"]
            )
            session.add(funding)
            stats.fundings += 1
        funding.amount_eur = item.get("amount_eur")
        funding.evidence_url = item.get("evidence_url")
        funding.note = item.get("note")
        await session.flush()
        await record(
            session,
            entity_type="source",
            entity_id=source.id,
            field=f"funding:{item['year']}",
            method="seed-import-v1",
            inputs={"seed": str(path.name), "program": item["program"]},
            source_name="Dipartimento per l'informazione e l'editoria",
            source_url=funding.evidence_url,
        )

    await session.flush()
    return stats


@dataclass
class OwnershipEntry:
    owner: Owner
    ownership: Ownership


@dataclass
class SourceProfile:
    source: Source
    ownerships: list[OwnershipEntry]
    fundings: list[PublicFunding]
    signals: list[BiasSignal]


async def source_profile(session: AsyncSession, slug: str) -> SourceProfile | None:
    source = (
        await session.execute(select(Source).where(Source.slug == slug))
    ).scalar_one_or_none()
    if source is None:
        return None
    rows = (
        await session.execute(
            select(Ownership, Owner)
            .join(Owner, Ownership.owner_id == Owner.id)
            .where(Ownership.source_id == source.id)
            .order_by(Owner.name)
        )
    ).all()
    fundings = (
        (
            await session.execute(
                select(PublicFunding)
                .where(PublicFunding.source_id == source.id)
                .order_by(PublicFunding.year.desc())
            )
        )
        .scalars()
        .all()
    )
    signals = (
        (
            await session.execute(
                select(BiasSignal)
                .where(BiasSignal.source_id == source.id)
                .order_by(BiasSignal.signal_type, BiasSignal.period_end.desc())
            )
        )
        .scalars()
        .all()
    )
    return SourceProfile(
        source=source,
        ownerships=[OwnershipEntry(owner=o, ownership=w) for w, o in rows],
        fundings=list(fundings),
        signals=list(signals),
    )


async def enrich_owner_from_wikidata(
    session: AsyncSession, owner: Owner, client: httpx.AsyncClient
) -> int:
    """Raccoglie fatti pubblici sul proprietario da Wikidata (CC0).

    Solo per proprietari con QID CONFERMATO nel seed (mai indovinato):
    cariche ricoperte con date, iscrizioni a partiti, occupazioni, aziende
    possedute, più i fatti societari. Tutto mostrato "secondo Wikidata".
    """
    from core.nlp.entity_link import (
        fact_years,
        fetch_entity,
        parse_company_claims,
        parse_person_claims,
        resolve_labels_keep_years,
    )

    if not owner.wikidata_qid:
        return 0
    entity = await fetch_entity(client, owner.wikidata_qid)
    raw_facts = parse_person_claims(entity) + [
        f for f in parse_company_claims(entity) if f.meaning != "inception"
    ]
    resolved = await resolve_labels_keep_years(client, raw_facts)
    facts: list[dict[str, object]] = []
    for fact in resolved:
        label, start, end = fact_years(fact)
        facts.append(
            {
                "meaning": fact.meaning,
                "label": label or fact.target_qid,
                "qid": fact.target_qid,
                "start": start,
                "end": end,
            }
        )
    owner.details = {"facts": facts, "retrieved_at": utcnow().isoformat()}
    await session.flush()
    await record(
        session,
        entity_type="owner",
        entity_id=owner.id,
        field="wikidata_facts",
        method="wikidata-owner-v1",
        inputs={"qid": owner.wikidata_qid, "n_facts": len(facts)},
        source_name="Wikidata",
        source_url=f"https://www.wikidata.org/wiki/{owner.wikidata_qid}",
    )
    return len(facts)

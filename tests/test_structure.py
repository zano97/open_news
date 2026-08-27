"""Fase 3: livello 1 — import seed proprietà/finanziamenti e pagine fonte."""

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core import provenance
from core.bias.structure import load_ownership_seed, source_profile
from core.ingest.catalog import sync_catalog
from core.models import Owner, Ownership, PublicFunding


async def test_seed_import_idempotente(session: AsyncSession) -> None:
    await sync_catalog(session)
    prima = await load_ownership_seed(session)
    assert prima.owners >= 15
    assert prima.ownerships >= 15
    assert prima.fundings >= 3

    seconda = await load_ownership_seed(session)
    assert seconda.owners == 0
    assert seconda.ownerships == 0
    assert seconda.fundings == 0

    owners = list((await session.execute(select(Owner))).scalars())
    assert len(owners) == prima.owners


async def test_profilo_fonte_con_evidenze(session: AsyncSession) -> None:
    await sync_catalog(session)
    await load_ownership_seed(session)

    profile = await source_profile(session, "libero")
    assert profile is not None
    assert profile.ownerships, "libero deve avere un proprietario registrato"
    angelucci = profile.ownerships[0].owner
    assert "Angelucci" in angelucci.name
    # La carica politica del proprietario è un fatto registrato con evidenza.
    assert angelucci.political_offices or any(
        e.owner.political_offices for e in profile.ownerships
    )

    prova = await provenance.for_entity(session, "source", profile.source.id)
    assert any(p.field.startswith("ownership:") for p in prova)


async def test_finanziamenti_senza_importo_dichiarati(session: AsyncSession) -> None:
    await sync_catalog(session)
    await load_ownership_seed(session)
    fundings = list((await session.execute(select(PublicFunding))).scalars())
    assert fundings
    # Il seed non inventa importi: se mancano, sono null con nota.
    for f in fundings:
        if f.amount_eur is None:
            assert f.note, "importo mancante senza nota esplicativa"


async def test_pagina_fonti(client: AsyncClient, session: AsyncSession) -> None:
    await sync_catalog(session)
    await session.commit()
    resp = await client.get("/fonti")
    assert resp.status_code == 200
    assert "la Repubblica" in resp.text
    # ANSA compare disabilitata con la motivazione.
    assert "disabilitata" in resp.text


async def test_pagina_fonte_completa(client: AsyncClient, session: AsyncSession) -> None:
    await sync_catalog(session)
    await load_ownership_seed(session)
    await session.commit()

    resp = await client.get("/fonte/libero")
    assert resp.status_code == 200
    testo = resp.text
    assert "Angelucci" in testo
    assert "grafo-proprieta" in testo  # il grafo SVG è inline
    assert "Da dove vengono questi dati?" in testo
    assert "carica politica" in testo

    resp404 = await client.get("/fonte/non-esiste")
    assert resp404.status_code == 404


async def test_pagina_fonte_dato_non_disponibile(
    client: AsyncClient, session: AsyncSession
) -> None:
    await sync_catalog(session)
    await session.commit()
    # Fonte senza seed proprietari: la pagina dichiara il dato mancante.
    resp = await client.get("/fonte/bbc-news")
    assert resp.status_code == 200
    assert "dato non disponibile" in resp.text


async def test_ownership_evidenze_presenti(session: AsyncSession) -> None:
    await sync_catalog(session)
    await load_ownership_seed(session)
    rows = list((await session.execute(select(Ownership))).scalars())
    assert rows
    for row in rows:
        assert row.evidence_name, "ogni partecipazione deve dichiarare l'evidenza"

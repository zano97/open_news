"""Fase 1: il catalogo fonti si carica, rispetta i vincoli e si sincronizza."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.ingest.catalog import load_catalog, sync_catalog
from core.models import Source


def test_catalogo_rispetta_i_vincoli_di_copertura() -> None:
    catalogo = load_catalog()
    assert len(catalogo) >= 40
    per_regione: dict[str, int] = {}
    for src in catalogo:
        per_regione[src.region] = per_regione.get(src.region, 0) + 1
    assert per_regione["italy"] >= 15
    assert per_regione["europe"] >= 10
    assert per_regione["world"] >= 15
    # Ogni fonte ha i campi obbligatori.
    for src in catalogo:
        assert src.slug and src.name and src.domain
        assert len(src.country) == 2
        assert src.terms_note, f"{src.slug} senza terms_note"

    ansa = next(s for s in catalogo if s.slug == "ansa")
    assert ansa.enabled is False
    assert ansa.disabled_reason


def test_slug_unici() -> None:
    catalogo = load_catalog()
    slugs = [s.slug for s in catalogo]
    assert len(slugs) == len(set(slugs))


def test_fonti_senza_rss_hanno_gdelt() -> None:
    for src in load_catalog():
        if not src.feed_urls and src.enabled:
            assert src.gdelt_domain, f"{src.slug} senza feed e senza gdelt_domain"


async def test_sync_idempotente(session: AsyncSession) -> None:
    prima = await sync_catalog(session)
    assert prima["created"] >= 40
    assert prima["updated"] == 0

    seconda = await sync_catalog(session)
    assert seconda["created"] == 0
    assert seconda["updated"] == prima["created"]

    ansa = (
        await session.execute(select(Source).where(Source.slug == "ansa"))
    ).scalar_one()
    assert ansa.enabled is False
    assert ansa.disabled_reason is not None


def test_catalogo_invarianti_di_qualita() -> None:
    """Regole che ogni voce del catalogo deve rispettare, per sempre:
    slug puliti, paesi ISO, feed https dentro l'allowlist e — per ogni
    fonte abilitata — un gdelt_domain: la copertura non deve mai dipendere
    solo dal feed."""
    import re
    from urllib.parse import urlsplit

    from core.net import host_allowed, reset_allowlist_cache

    reset_allowlist_cache()
    for src in load_catalog():
        assert re.fullmatch(r"[a-z0-9-]+", src.slug), src.slug
        assert re.fullmatch(r"[a-z]{2}", src.country), (src.slug, src.country)
        assert src.language, src.slug
        assert src.name.strip(), src.slug
        if src.enabled:
            assert src.gdelt_domain, f"{src.slug}: fonte abilitata senza gdelt_domain"
        for url in src.feed_urls:
            assert url.startswith("https://"), (src.slug, url)
            host = urlsplit(url).hostname
            assert host and host_allowed(host), (src.slug, url)

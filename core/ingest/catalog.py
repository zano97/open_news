"""Catalogo delle fonti: data/sources.yaml è la fonte di verità.

`sync_catalog` riversa il catalogo nel DB in modo idempotente: le fonti sono
riconosciute per `slug`; i campi anagrafici vengono aggiornati dal file. Lo
stato `enabled` scritto da `make verify-feeds` vive nel file stesso, quindi
catalogo e DB non possono divergere.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import DATA_DIR
from core.models import Source

CATALOG_PATH = DATA_DIR / "sources.yaml"


@dataclass(frozen=True)
class CatalogSource:
    slug: str
    name: str
    domain: str
    country: str
    language: str
    region: str
    feed_urls: tuple[str, ...] = ()
    gdelt_domain: str | None = None
    wikidata_qid: str | None = None
    founded: int | None = None
    enabled: bool = True
    disabled_reason: str | None = None
    terms_note: str = ""
    self_declared_line: dict[str, str] | None = None
    # Canali social UFFICIALI della testata, usati come canale di raccolta
    # aggiuntivo (vedi core/ingest/social.py): {"bluesky": handle,
    # "mastodon": "https://istanza/@account"}.
    social: dict[str, str] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)


def load_catalog(path: Path = CATALOG_PATH) -> list[CatalogSource]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    sources: list[CatalogSource] = []
    for item in raw["sources"]:
        known = {
            "slug", "name", "domain", "country", "language", "region", "feed_urls",
            "gdelt_domain", "wikidata_qid", "founded", "enabled", "disabled_reason",
            "terms_note", "self_declared_line", "social",
        }
        extra = {k: v for k, v in item.items() if k not in known}
        sources.append(
            CatalogSource(
                slug=item["slug"],
                name=item["name"],
                domain=item["domain"],
                country=item["country"],
                language=item["language"],
                region=item.get("region", "world"),
                feed_urls=tuple(item.get("feed_urls") or ()),
                gdelt_domain=item.get("gdelt_domain"),
                wikidata_qid=item.get("wikidata_qid"),
                founded=item.get("founded"),
                enabled=bool(item.get("enabled", True)),
                disabled_reason=item.get("disabled_reason"),
                terms_note=(item.get("terms_note") or "").strip(),
                self_declared_line=item.get("self_declared_line"),
                social={
                    str(k): str(v) for k, v in (item.get("social") or {}).items()
                },
                extra=extra,
            )
        )
    return sources


async def sync_catalog(
    session: AsyncSession, path: Path = CATALOG_PATH
) -> dict[str, int]:
    """Upsert idempotente del catalogo nel DB. Ritorna {created, updated}."""
    catalog = load_catalog(path)
    existing = {
        s.slug: s for s in (await session.execute(select(Source))).scalars()
    }
    created = updated = 0
    for entry in catalog:
        row = existing.get(entry.slug)
        if row is None:
            row = Source(slug=entry.slug)
            session.add(row)
            created += 1
        else:
            updated += 1
        row.name = entry.name
        row.domain = entry.domain
        row.country = entry.country
        row.language = entry.language
        row.region = entry.region
        row.feed_urls = list(entry.feed_urls)
        row.gdelt_domain = entry.gdelt_domain
        row.wikidata_qid = entry.wikidata_qid
        row.founded = entry.founded
        row.enabled = entry.enabled
        row.disabled_reason = entry.disabled_reason
        row.terms_note = entry.terms_note
        row.self_declared_line = entry.self_declared_line
    await session.flush()
    return {"created": created, "updated": updated}

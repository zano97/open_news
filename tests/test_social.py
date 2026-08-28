"""Canali social delle testate: parsing, filtro sul dominio, dedup, provenance."""

from datetime import UTC, datetime

import httpx
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core import provenance
from core.ingest.ratelimit import DomainRateLimiter
from core.ingest.social import (
    SocialItem,
    fetch_bluesky_items,
    fetch_mastodon_items,
    parse_bluesky_feed,
    parse_mastodon_statuses,
    split_mastodon_account,
    store_social_items,
    verified_handle,
)
from core.models import Article, Source


def _fonte() -> Source:
    return Source(
        slug="esempio-social",
        name="Quotidiano d'Esempio",
        domain="esempio.test",
        country="it",
        language="it",
        region="italy",
        feed_urls=[],
        gdelt_domain="esempio.test",
        terms_note="",
    )


class FakeClock:
    def __init__(self) -> None:
        self.time = 0.0

    def now(self) -> float:
        return self.time

    async def sleep(self, seconds: float) -> None:
        self.time += seconds


def _limiter() -> DomainRateLimiter:
    clock = FakeClock()
    return DomainRateLimiter(min_interval=2.0, now=clock.now, sleep=clock.sleep)


BLUESKY_PAYLOAD = {
    "feed": [
        {  # post con scheda-link a un articolo della testata
            "post": {
                "uri": "at://did:plc:x/app.bsky.feed.post/abc123",
                "record": {"createdAt": "2026-08-28T08:00:00Z"},
                "embed": {
                    "$type": "app.bsky.embed.external#view",
                    "external": {
                        "uri": "https://esempio.test/politica/riforma?utm_source=bsky",
                        "title": "Il governo approva la riforma delle pensioni",
                        "description": "Dopo mesi di trattative arriva il via libera.",
                    },
                },
            }
        },
        {  # repost: non è una pubblicazione della testata
            "reason": {"$type": "app.bsky.feed.defs#reasonRepost"},
            "post": {
                "uri": "at://did:plc:y/app.bsky.feed.post/zzz",
                "embed": {
                    "$type": "app.bsky.embed.external#view",
                    "external": {
                        "uri": "https://esempio.test/da-non-prendere",
                        "title": "Repost altrui",
                    },
                },
            },
        },
        {  # post senza scheda-link: niente da raccogliere
            "post": {"uri": "at://did:plc:x/app.bsky.feed.post/def", "record": {}}
        },
        {  # scheda-link verso un ALTRO dominio: si scarta allo store
            "post": {
                "uri": "at://did:plc:x/app.bsky.feed.post/ghi456",
                "record": {"createdAt": "2026-08-28T07:00:00Z"},
                "embed": {
                    "$type": "app.bsky.embed.external#view",
                    "external": {
                        "uri": "https://altrove.test/articolo",
                        "title": "Articolo di terzi",
                    },
                },
            }
        },
    ]
}

MASTODON_STATUSES = [
    {  # status con card verso il dominio della testata
        "url": "https://mastodon.esempio.test/@esempio/1",
        "created_at": "2026-08-28T06:30:00Z",
        "card": {
            "url": "https://esempio.test/cronaca/alluvione-nord",
            "title": "Alluvione nel nord: migliaia di sfollati",
            "description": "Esondazioni in tre province.",
        },
    },
    {"url": "https://mastodon.esempio.test/@esempio/2", "card": None},  # senza card
]


def test_parse_bluesky_feed() -> None:
    items = parse_bluesky_feed(BLUESKY_PAYLOAD, "esempio.test")
    assert len(items) == 2  # il repost e il post senza scheda restano fuori
    primo = items[0]
    assert primo.title.startswith("Il governo approva")
    assert primo.posted_at == datetime(2026, 8, 28, 8, 0, tzinfo=UTC)
    assert primo.post_url == "https://bsky.app/profile/esempio.test/post/abc123"
    assert primo.platform == "bluesky"


def test_parse_mastodon_statuses() -> None:
    items = parse_mastodon_statuses(MASTODON_STATUSES)
    assert len(items) == 1
    assert items[0].url == "https://esempio.test/cronaca/alluvione-nord"
    assert items[0].post_url == "https://mastodon.esempio.test/@esempio/1"
    assert items[0].platform == "mastodon"


def test_split_mastodon_account() -> None:
    assert split_mastodon_account("https://ard.social/@tagesschau") == (
        "https://ard.social", "tagesschau",
    )
    assert split_mastodon_account("https://ard.social/tagesschau") is None
    assert split_mastodon_account("non-un-url") is None


def test_verified_handle() -> None:
    """Su Bluesky si accettano SOLO handle a dominio della testata:
    l'autenticità la garantisce il protocollo, mai la somiglianza del nome."""
    fonte = _fonte()
    assert verified_handle("esempio.test", fonte)
    assert verified_handle("@esempio.test", fonte)
    assert verified_handle("news.esempio.test", fonte)
    assert not verified_handle("esempio-news.bsky.social", fonte)
    assert not verified_handle("esempio.test.impostore.com", fonte)


@respx.mock
async def test_fetch_e_store_bluesky(session: AsyncSession) -> None:
    fonte = _fonte()
    session.add(fonte)
    await session.flush()

    respx.get("https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed").mock(
        return_value=httpx.Response(200, json=BLUESKY_PAYLOAD)
    )
    async with httpx.AsyncClient() as client:
        items = await fetch_bluesky_items(client, _limiter(), "esempio.test")
    creati = await store_social_items(session, fonte, items)
    assert creati == 1  # il link di terzi non entra mai

    articolo = (
        await session.execute(select(Article).where(Article.source_id == fonte.id))
    ).scalar_one()
    assert articolo.title == "Il governo approva la riforma delle pensioni"
    assert "trattative" in articolo.snippet
    prova = await provenance.for_entity(session, "article", articolo.id)
    riga = next(p for p in prova if p.field == "ingest")
    assert riga.method == "bluesky-public-api"
    assert riga.source_name == "Bluesky"

    # Idempotente: lo stesso giro non duplica (URL e canonico già noti).
    assert await store_social_items(session, fonte, items) == 0


@respx.mock
async def test_fetch_mastodon(session: AsyncSession) -> None:
    respx.get("https://mastodon.esempio.test/api/v1/accounts/lookup").mock(
        return_value=httpx.Response(200, json={"id": "42"})
    )
    respx.get("https://mastodon.esempio.test/api/v1/accounts/42/statuses").mock(
        return_value=httpx.Response(200, json=MASTODON_STATUSES)
    )
    async with httpx.AsyncClient() as client:
        items = await fetch_mastodon_items(
            client, _limiter(), "https://mastodon.esempio.test/@esempio"
        )
    assert [i.url for i in items] == ["https://esempio.test/cronaca/alluvione-nord"]


async def test_store_non_duplica_articolo_dal_feed(session: AsyncSession) -> None:
    """Un articolo già arrivato dal feed non si duplica quando la testata
    lo posta sui social (dedup per URL canonico: gli utm dei social cadono)."""
    fonte = _fonte()
    session.add(fonte)
    await session.flush()
    session.add(
        Article(
            source_id=fonte.id,
            url="https://esempio.test/politica/riforma",
            canonical_url="https://esempio.test/politica/riforma",
            title="Il governo approva la riforma delle pensioni",
            snippet="Dal feed.",
            language="it",
        )
    )
    await session.flush()

    item = SocialItem(
        url="https://esempio.test/politica/riforma?utm_source=bsky",
        title="Il governo approva la riforma delle pensioni",
        description="…",
        posted_at=None,
        post_url="https://bsky.app/profile/esempio.test/post/abc",
        platform="bluesky",
    )
    assert await store_social_items(session, fonte, [item]) == 0


def test_allowlist_include_bluesky_e_istanze_mastodon() -> None:
    """L'egress resta chiuso: Bluesky è statico, le istanze Mastodon
    entrano SOLO se dichiarate nel catalogo."""
    from core.net import host_allowed, reset_allowlist_cache

    reset_allowlist_cache()
    assert host_allowed("public.api.bsky.app")
    assert host_allowed("ard.social")  # dal canale di tagesschau nel catalogo
    assert not host_allowed("instagram.com")
    assert not host_allowed("x.com")
    reset_allowlist_cache()

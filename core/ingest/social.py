"""Canali social UFFICIALI delle testate come canale di raccolta aggiuntivo.

Il principio: il profilo social ufficiale di una testata è un altro posto
dove la testata pubblica i PROPRI articoli. Dei post si usano solo i
metadati della scheda-link (titolo, descrizione breve, URL dell'articolo):
il testo del post non viene conservato, e contano solo i post che linkano
il dominio della testata stessa — mai contenuti di terzi. Stessa impronta
legale di GDELT (titolo+snippet+link) e stesso dedup per URL: un articolo
già arrivato dal feed non si duplica, uno visto solo sui social si
aggiunge — e con lui migliorano copertura e angoli ciechi.

Piattaforme: SOLO API pubbliche, gratuite e senza chiave (vedi NOTICE).
- Bluesky: AppView pubblica (public.api.bsky.app). Si accettano SOLO
  handle a dominio verificato — l'handle È il dominio della testata,
  l'autenticità la garantisce il protocollo (impersonare è impossibile).
- Mastodon: API pubblica dell'istanza indicata nel catalogo.

X (Twitter) e Instagram non offrono oggi un accesso programmatico
gratuito e lecito (API a pagamento, scraping vietato dai termini d'uso):
restano fuori finché è così. Vedi ADR-0023 e docs/METHODOLOGY.md.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.extract.canonical import canonicalize
from core.extract.dedup import is_near_duplicate, simhash64, to_hex
from core.ingest.ratelimit import DomainRateLimiter
from core.ingest.rss import _recent_simhashes, make_snippet
from core.models import Article, Source
from core.provenance import record

log = logging.getLogger(__name__)

BLUESKY_HOST = "public.api.bsky.app"
BLUESKY_FEED_URL = f"https://{BLUESKY_HOST}/xrpc/app.bsky.feed.getAuthorFeed"


@dataclass(frozen=True)
class SocialItem:
    """Un articolo linkato da un post social: solo metadati della scheda."""

    url: str
    title: str
    description: str
    posted_at: datetime | None
    post_url: str
    platform: str  # "bluesky" | "mastodon"


def _parse_iso(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def verified_handle(handle: str, source: Source) -> bool:
    """Vero se l'handle Bluesky è il dominio (verificato) della testata.

    Su Bluesky un handle a dominio è autenticato dal protocollo (DNS o
    /.well-known): accettando SOLO quelli, un account impostore non può
    mai entrare nel catalogo per errore di battitura o omonimia.
    """
    pulito = handle.lower().strip().rstrip(".").removeprefix("@")
    domini = {source.domain.lower()}
    if source.gdelt_domain:
        domini.add(source.gdelt_domain.lower())
    return any(pulito == d or pulito.endswith("." + d) for d in domini)


def parse_bluesky_feed(payload: dict[str, Any], handle: str) -> list[SocialItem]:
    """Estrae le schede-link dai post dell'autore (mai dai repost)."""
    items: list[SocialItem] = []
    for entry in payload.get("feed", []) or []:
        if entry.get("reason"):  # repost: non è una pubblicazione della testata
            continue
        post = entry.get("post") or {}
        embed = post.get("embed") or {}
        if str(embed.get("$type", "")) != "app.bsky.embed.external#view":
            continue
        external = embed.get("external") or {}
        url = external.get("uri")
        title = str(external.get("title") or "").strip()
        if not url or not title:
            continue
        record_ = post.get("record") or {}
        rkey = str(post.get("uri") or "").rsplit("/", 1)[-1]
        items.append(
            SocialItem(
                url=str(url),
                title=title,
                description=str(external.get("description") or ""),
                posted_at=_parse_iso(record_.get("createdAt") or post.get("indexedAt")),
                post_url=(
                    f"https://bsky.app/profile/{handle}/post/{rkey}" if rkey else ""
                ),
                platform="bluesky",
            )
        )
    return items


async def fetch_bluesky_items(
    client: httpx.AsyncClient,
    limiter: DomainRateLimiter,
    handle: str,
    *,
    limit: int = 30,
) -> list[SocialItem]:
    await limiter.wait(BLUESKY_HOST)
    resp = await client.get(
        BLUESKY_FEED_URL,
        params={
            "actor": handle,
            "limit": str(limit),
            "filter": "posts_no_replies",
        },
    )
    resp.raise_for_status()
    payload = resp.json()
    return parse_bluesky_feed(payload if isinstance(payload, dict) else {}, handle)


def split_mastodon_account(account_url: str) -> tuple[str, str] | None:
    """Da "https://istanza/@account" a (base dell'istanza, account)."""
    parts = urlsplit(account_url)
    acct = parts.path.strip("/")
    if not parts.hostname or not acct.startswith("@"):
        return None
    return f"https://{parts.hostname}", acct[1:]


def parse_mastodon_statuses(payload: list[dict[str, Any]]) -> list[SocialItem]:
    """Estrae le schede-link ("card") dagli status pubblici."""
    items: list[SocialItem] = []
    for status in payload or []:
        card = status.get("card") or {}
        url = card.get("url")
        title = str(card.get("title") or "").strip()
        if not url or not title:
            continue
        items.append(
            SocialItem(
                url=str(url),
                title=title,
                description=str(card.get("description") or ""),
                posted_at=_parse_iso(status.get("created_at")),
                post_url=str(status.get("url") or ""),
                platform="mastodon",
            )
        )
    return items


async def fetch_mastodon_items(
    client: httpx.AsyncClient,
    limiter: DomainRateLimiter,
    account_url: str,
    *,
    limit: int = 30,
) -> list[SocialItem]:
    parsed = split_mastodon_account(account_url)
    if parsed is None:
        log.warning("account Mastodon malformato nel catalogo: %s", account_url)
        return []
    base, acct = parsed
    host = urlsplit(base).hostname or ""
    await limiter.wait(host)
    lookup = await client.get(f"{base}/api/v1/accounts/lookup", params={"acct": acct})
    lookup.raise_for_status()
    account_id = (lookup.json() or {}).get("id")
    if not account_id:
        return []
    await limiter.wait(host)
    resp = await client.get(
        f"{base}/api/v1/accounts/{account_id}/statuses",
        params={
            "limit": str(limit),
            "exclude_replies": "true",
            "exclude_reblogs": "true",
        },
    )
    resp.raise_for_status()
    payload = resp.json()
    return parse_mastodon_statuses(payload if isinstance(payload, list) else [])


def _belongs_to_source(url: str, source: Source) -> bool:
    host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    if not host:
        return False
    domini = {source.domain.lower()}
    if source.gdelt_domain:
        domini.add(source.gdelt_domain.lower())
    return any(host == d or host.endswith("." + d) for d in domini)


async def store_social_items(
    session: AsyncSession, source: Source, items: list[SocialItem]
) -> int:
    """Registra come articoli i link della testata trovati nei suoi post.

    Solo link al dominio della testata; dedup per URL, URL canonico e
    quasi-duplicati (come per i feed). Idempotente.
    """
    keep = [i for i in items if _belongs_to_source(i.url, source)]
    if not keep:
        return 0
    urls = [i.url for i in keep]
    canonicals = [canonicalize(u) for u in urls]
    known_urls = set(
        (
            await session.execute(select(Article.url).where(Article.url.in_(urls)))
        ).scalars()
    )
    known_canonicals = {
        c
        for c in (
            await session.execute(
                select(Article.canonical_url).where(
                    Article.canonical_url.in_(canonicals)
                )
            )
        ).scalars()
        if c
    }
    recent_hashes = await _recent_simhashes(session, source.id)
    created = 0
    for item in keep:
        canonical = canonicalize(item.url)
        if item.url in known_urls or canonical in known_canonicals:
            continue
        snippet = make_snippet(item.description)
        fingerprint = simhash64(f"{item.title} {snippet}")
        if any(is_near_duplicate(fingerprint, h) for h in recent_hashes):
            continue
        article = Article(
            source_id=source.id,
            url=item.url,
            canonical_url=canonical,
            title=item.title,
            snippet=snippet,
            published_at=item.posted_at,
            language=source.language,
            simhash=to_hex(fingerprint),
        )
        session.add(article)
        await session.flush()
        await record(
            session,
            entity_type="article",
            entity_id=article.id,
            field="ingest",
            method=f"{item.platform}-public-api",
            inputs={"post": item.post_url},
            source_name="Bluesky" if item.platform == "bluesky" else "Mastodon",
            source_url=item.post_url or None,
        )
        known_urls.add(item.url)
        known_canonicals.add(canonical)
        recent_hashes.append(fingerprint)
        created += 1
    return created

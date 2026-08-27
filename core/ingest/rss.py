"""Ingestione RSS/Atom: fetch condizionale (ETag/Last-Modified), parsing, upsert.

Il parsing è separato dall'I/O per essere testabile su fixture registrate.
Vincolo legale (docs/LEGAL.md): dello snippet si conservano al massimo
SNIPPET_MAX_CHARS caratteri; il feed fornisce solo ciò che l'editore ha scelto
di pubblicare nel feed stesso.
"""

import html
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from time import struct_time
from typing import Any
from urllib.parse import urlsplit

import feedparser
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.extract.canonical import canonicalize
from core.extract.dedup import from_hex, is_near_duplicate, simhash64, to_hex
from core.extract.language import detect_language
from core.ingest.ratelimit import DomainRateLimiter
from core.ingest.robots import RobotsCache
from core.models import SNIPPET_MAX_CHARS, Article, FeedState, Source, utcnow

log = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class FeedEntry:
    url: str
    title: str
    snippet: str
    image_url: str | None
    published_at: datetime | None
    authors: tuple[str, ...]


@dataclass
class IngestStats:
    fetched: int = 0
    created: int = 0
    skipped_existing: int = 0
    skipped_duplicates: int = 0
    not_modified: bool = False
    error: str | None = None


def make_snippet(raw_html: str | None) -> str:
    """Testo puro, spazi normalizzati, troncato a parola entro il limite legale."""
    if not raw_html:
        return ""
    text = _WS_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", raw_html))).strip()
    if len(text) <= SNIPPET_MAX_CHARS:
        return text
    cut = text[: SNIPPET_MAX_CHARS - 1]
    if " " in cut:
        cut = cut[: cut.rindex(" ")]
    return cut + "…"


def _struct_to_datetime(value: struct_time | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime(*value[:6], tzinfo=UTC)
    except (ValueError, TypeError):
        return None


def _entry_image(entry: Any) -> str | None:
    for media in entry.get("media_content", []) or []:
        if media.get("url"):
            return str(media["url"])
    for thumb in entry.get("media_thumbnail", []) or []:
        if thumb.get("url"):
            return str(thumb["url"])
    for link in entry.get("links", []) or []:
        if link.get("rel") == "enclosure" and str(link.get("type", "")).startswith("image/"):
            return str(link.get("href"))
    return None


def _entry_authors(entry: Any) -> tuple[str, ...]:
    names = [a.get("name") for a in entry.get("authors", []) or [] if a.get("name")]
    if not names and entry.get("author"):
        names = [entry["author"]]
    return tuple(str(n).strip() for n in names if str(n).strip())


def parse_feed(content: bytes) -> list[FeedEntry]:
    parsed = feedparser.parse(content)
    entries: list[FeedEntry] = []
    for entry in parsed.entries:
        url = entry.get("link")
        title = _WS_RE.sub(" ", html.unescape(entry.get("title", "")).strip())
        if not url or not title:
            continue
        summary = entry.get("summary") or entry.get("description") or ""
        published = _struct_to_datetime(
            entry.get("published_parsed") or entry.get("updated_parsed")
        )
        entries.append(
            FeedEntry(
                url=str(url),
                title=title,
                snippet=make_snippet(str(summary)),
                image_url=_entry_image(entry),
                published_at=published,
                authors=_entry_authors(entry),
            )
        )
    return entries


async def _feed_state(session: AsyncSession, source: Source, feed_url: str) -> FeedState:
    state = (
        await session.execute(select(FeedState).where(FeedState.feed_url == feed_url))
    ).scalar_one_or_none()
    if state is None:
        state = FeedState(source_id=source.id, feed_url=feed_url)
        session.add(state)
        await session.flush()
    return state


async def _recent_simhashes(
    session: AsyncSession, source_id: int, limit: int = 300
) -> list[int]:
    rows = (
        await session.execute(
            select(Article.simhash)
            .where(Article.source_id == source_id, Article.simhash.is_not(None))
            .order_by(Article.id.desc())
            .limit(limit)
        )
    ).scalars()
    return [from_hex(h) for h in rows if h]


async def ingest_feed(
    session: AsyncSession,
    source: Source,
    feed_url: str,
    *,
    client: httpx.AsyncClient,
    limiter: DomainRateLimiter,
    robots: RobotsCache,
) -> IngestStats:
    """Scarica un feed (se cambiato) e inserisce gli articoli nuovi. Idempotente."""
    stats = IngestStats()
    host = urlsplit(feed_url).hostname or source.domain

    if not await robots.can_fetch(feed_url):
        stats.error = f"robots.txt vieta l'accesso a {feed_url}"
        log.warning(stats.error)
        return stats

    state = await _feed_state(session, source, feed_url)
    headers: dict[str, str] = {}
    if state.etag:
        headers["If-None-Match"] = state.etag
    if state.last_modified:
        headers["If-Modified-Since"] = state.last_modified

    await limiter.wait(host)
    try:
        resp = await client.get(feed_url, headers=headers)
    except httpx.HTTPError as exc:
        stats.error = f"fetch fallito: {exc}"
        state.error = stats.error
        state.last_fetched_at = utcnow()
        log.warning("feed %s: %s", feed_url, stats.error)
        return stats

    state.last_status = resp.status_code
    state.last_fetched_at = utcnow()
    state.error = None

    if resp.status_code == 304:
        stats.not_modified = True
        return stats
    if resp.status_code != 200:
        stats.error = f"HTTP {resp.status_code}"
        state.error = stats.error
        return stats

    state.etag = resp.headers.get("ETag")
    state.last_modified = resp.headers.get("Last-Modified")

    entries = parse_feed(resp.content)
    stats.fetched = len(entries)
    if not entries:
        return stats

    known_urls = set(
        (
            await session.execute(
                select(Article.url).where(Article.url.in_([e.url for e in entries]))
            )
        ).scalars()
    )
    known_canonicals = {
        c
        for c in (
            await session.execute(
                select(Article.canonical_url).where(
                    Article.canonical_url.in_([canonicalize(e.url) for e in entries])
                )
            )
        ).scalars()
        if c
    }
    recent_hashes = await _recent_simhashes(session, source.id)

    for entry in entries:
        canonical = canonicalize(entry.url)
        if entry.url in known_urls or canonical in known_canonicals:
            stats.skipped_existing += 1
            continue
        fingerprint = simhash64(f"{entry.title} {entry.snippet}")
        if any(is_near_duplicate(fingerprint, h) for h in recent_hashes):
            stats.skipped_duplicates += 1
            continue
        guess = detect_language(f"{entry.title}. {entry.snippet}")
        session.add(
            Article(
                source_id=source.id,
                url=entry.url,
                canonical_url=canonical,
                title=entry.title,
                snippet=entry.snippet,
                image_url=entry.image_url,
                published_at=entry.published_at,
                language=guess.language or source.language,
                authors=list(entry.authors),
                simhash=to_hex(fingerprint),
            )
        )
        known_urls.add(entry.url)
        known_canonicals.add(canonical)
        recent_hashes.append(fingerprint)
        stats.created += 1

    await session.flush()
    return stats

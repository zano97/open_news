"""Ingestione RSS/Atom: fetch condizionale (ETag/Last-Modified), parsing, upsert.

Il parsing è separato dall'I/O per essere testabile su fixture registrate;
la fase di rete (`fetch_feed_content`) è separata da quella di scrittura
(`store_feed`) così più feed possono essere scaricati in parallelo mentre il
database — che su SQLite ha un solo scrittore — viene toccato in sequenza.

Robustezza: se l'URL del catalogo risponde 404/410 o restituisce HTML, si
tenta l'autodiscovery del feed dalla homepage (`<link rel="alternate">`) e
l'URL trovato viene ricordato in FeedState.resolved_url; un feed che continua
a fallire entra in backoff e viene riprovato con calma.

Vincolo legale (docs/LEGAL.md): dello snippet si conservano al massimo
SNIPPET_MAX_CHARS caratteri; il feed fornisce solo ciò che l'editore ha scelto
di pubblicare nel feed stesso.
"""

import html
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import struct_time
from typing import Any
from urllib.parse import urljoin, urlsplit

import feedparser
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from core.extract.canonical import canonicalize
from core.extract.dedup import from_hex, is_near_duplicate, simhash64, to_hex
from core.extract.language import detect_language
from core.ingest.ratelimit import DomainRateLimiter
from core.ingest.robots import RobotsCache
from core.models import SNIPPET_MAX_CHARS, Article, FeedState, Source, utcnow
from core.net import EgressDeniedError

log = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_ALTERNATE_LINK_RE = re.compile(r"<link\b[^>]*>", re.IGNORECASE)
_ATTR_RE = re.compile(r"""([a-zA-Z-]+)\s*=\s*["']([^"']*)["']""")
_FEED_TYPES = {"application/rss+xml", "application/atom+xml"}


def describe_error(exc: Exception) -> str:
    """Messaggio leggibile anche per le eccezioni httpx senza testo (timeout)."""
    text = str(exc).strip()
    return f"{exc.__class__.__name__}: {text}" if text else exc.__class__.__name__


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
    # Feed in pausa dopo errori ripetuti: nessun tentativo in questo giro.
    backoff: bool = False


@dataclass
class FeedFetch:
    """Esito della sola fase di rete, senza alcun accesso al database."""

    requested_url: str
    status_code: int | None = None
    content: bytes = b""
    etag: str | None = None
    last_modified: str | None = None
    error: str | None = None
    not_modified: bool = False
    # Se l'URL richiesto era morto ma l'autodiscovery ha trovato un feed
    # funzionante sul dominio della testata, eccolo.
    discovered_url: str | None = None


def discover_feed_links(page_html: str, base_url: str) -> list[str]:
    """URL dei feed dichiarati nella pagina via <link rel="alternate">."""
    found: list[str] = []
    for tag in _ALTERNATE_LINK_RE.findall(page_html):
        attrs = {k.lower(): v for k, v in _ATTR_RE.findall(tag)}
        if "alternate" not in attrs.get("rel", "").lower():
            continue
        if attrs.get("type", "").split(";")[0].strip().lower() not in _FEED_TYPES:
            continue
        href = attrs.get("href", "").strip()
        if href:
            url = urljoin(base_url, href)
            if url.startswith("http") and url not in found:
                found.append(url)
    return found


def _looks_like_html(content: bytes) -> bool:
    head = content[:2048].lstrip().lower()
    return head.startswith(b"<!doctype html") or b"<html" in head


async def _try_autodiscovery(
    domain: str,
    original_url: str,
    *,
    client: httpx.AsyncClient,
    limiter: DomainRateLimiter,
    robots: RobotsCache,
) -> FeedFetch | None:
    """Cerca un feed alternativo sulla homepage della testata e lo prova."""
    homepage = f"https://{domain}/"
    if not await robots.can_fetch(homepage):
        return None
    await limiter.wait(domain)
    try:
        resp = await client.get(homepage)
    except (httpx.HTTPError, EgressDeniedError):
        return None
    if resp.status_code != 200:
        return None
    candidates = [
        url
        for url in discover_feed_links(resp.text, homepage)
        if url != original_url
        and (urlsplit(url).hostname or "").lower().endswith(domain.lower())
    ]
    for candidate in candidates[:2]:
        if not await robots.can_fetch(candidate):
            continue
        await limiter.wait(urlsplit(candidate).hostname or domain)
        try:
            cand_resp = await client.get(candidate)
        except (httpx.HTTPError, EgressDeniedError):
            continue
        if cand_resp.status_code == 200 and parse_feed(cand_resp.content):
            log.info("feed %s irraggiungibile: uso %s (autodiscovery)", original_url, candidate)
            return FeedFetch(
                requested_url=original_url,
                status_code=200,
                content=cand_resp.content,
                etag=cand_resp.headers.get("ETag"),
                last_modified=cand_resp.headers.get("Last-Modified"),
                discovered_url=candidate,
            )
    return None


async def fetch_feed_content(
    feed_url: str,
    *,
    client: httpx.AsyncClient,
    limiter: DomainRateLimiter,
    robots: RobotsCache,
    etag: str | None = None,
    last_modified: str | None = None,
    discovery_domain: str | None = None,
) -> FeedFetch:
    """Scarica un feed (solo rete): robots, rate limit, cache condizionale.

    Con `discovery_domain`, un 404/410 o una risposta HTML fanno scattare
    l'autodiscovery del feed dalla homepage di quel dominio.
    """
    fetch = FeedFetch(requested_url=feed_url)
    host = urlsplit(feed_url).hostname or discovery_domain or ""

    if not await robots.can_fetch(feed_url):
        fetch.error = f"robots.txt vieta l'accesso a {feed_url}"
        return fetch

    headers: dict[str, str] = {}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    await limiter.wait(host)
    try:
        resp = await client.get(feed_url, headers=headers)
    except (httpx.HTTPError, EgressDeniedError) as exc:
        fetch.error = f"fetch fallito: {describe_error(exc)}"
        return fetch

    fetch.status_code = resp.status_code
    if resp.status_code == 304:
        fetch.not_modified = True
        return fetch

    needs_discovery = resp.status_code in (404, 410) or (
        resp.status_code == 200
        and not parse_feed(resp.content)
        and _looks_like_html(resp.content)
    )
    if needs_discovery and discovery_domain:
        discovered = await _try_autodiscovery(
            discovery_domain, feed_url, client=client, limiter=limiter, robots=robots
        )
        if discovered is not None:
            return discovered

    if resp.status_code != 200:
        fetch.error = f"HTTP {resp.status_code}"
        return fetch

    fetch.content = resp.content
    fetch.etag = resp.headers.get("ETag")
    fetch.last_modified = resp.headers.get("Last-Modified")
    return fetch


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


def in_backoff(state: FeedState) -> bool:
    """Vero se il feed ha fallito troppe volte di fila ed è presto per riprovare."""
    settings = get_settings()
    if state.consecutive_failures < settings.feed_backoff_failures:
        return False
    if state.last_fetched_at is None:
        return False
    return utcnow() - state.last_fetched_at < timedelta(hours=settings.feed_backoff_hours)


async def store_feed(
    session: AsyncSession,
    source: Source,
    feed_url: str,
    fetch: FeedFetch,
) -> IngestStats:
    """Registra l'esito di rete e inserisce gli articoli nuovi. Idempotente."""
    stats = IngestStats()
    state = await _feed_state(session, source, feed_url)
    state.last_fetched_at = utcnow()
    if fetch.status_code is not None:
        state.last_status = fetch.status_code

    if fetch.error:
        stats.error = fetch.error
        state.error = fetch.error
        state.consecutive_failures += 1
        log.warning("feed %s: %s", feed_url, fetch.error)
        return stats

    state.error = None
    state.consecutive_failures = 0
    if fetch.not_modified:
        stats.not_modified = True
        return stats

    if fetch.discovered_url:
        state.resolved_url = fetch.discovered_url
    state.etag = fetch.etag
    state.last_modified = fetch.last_modified

    entries = parse_feed(fetch.content)
    stats.fetched = len(entries)
    if not entries:
        stats.error = "feed vuoto o non interpretabile"
        state.error = stats.error
        state.consecutive_failures += 1
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


async def ingest_feed(
    session: AsyncSession,
    source: Source,
    feed_url: str,
    *,
    client: httpx.AsyncClient,
    limiter: DomainRateLimiter,
    robots: RobotsCache,
    retry_failed: bool = True,
) -> IngestStats:
    """Scarica un feed (se cambiato) e inserisce gli articoli nuovi.

    Composizione di `fetch_feed_content` + `store_feed` per l'uso sequenziale;
    per molti feed in parallelo vedi `core.ingest.pipeline`.
    """
    state = await _feed_state(session, source, feed_url)
    if not retry_failed and in_backoff(state):
        return IngestStats(backoff=True)
    fetch = await fetch_feed_content(
        state.resolved_url or feed_url,
        client=client,
        limiter=limiter,
        robots=robots,
        etag=state.etag,
        last_modified=state.last_modified,
        discovery_domain=source.domain,
    )
    fetch.requested_url = feed_url
    return await store_feed(session, source, feed_url, fetch)

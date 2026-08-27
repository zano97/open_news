"""Rispetto di robots.txt, con cache per host e TTL.

Politica: se robots.txt non esiste (4xx) l'accesso è consentito, come da
consuetudine; se il fetch fallisce (rete, 5xx) l'accesso è consentito ma
l'evento viene loggato — il rate limit resta comunque attivo.
"""

import logging
import time
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from core.config import get_settings

log = logging.getLogger(__name__)


class RobotsCache:
    def __init__(self, client: httpx.AsyncClient, ttl_seconds: float = 3600.0) -> None:
        self._client = client
        self._ttl = ttl_seconds
        self._cache: dict[str, tuple[float, RobotFileParser | None]] = {}
        # Per le regole robots conta il token del bot ("OpenNewsBot"), non
        # l'header HTTP completo: un sito che ci vieta per nome va rispettato
        # anche se l'header inizia con "Mozilla/5.0 (compatible; ...)".
        self._user_agent = get_settings().robots_user_agent

    async def _load(self, scheme: str, host: str) -> RobotFileParser | None:
        url = f"{scheme}://{host}/robots.txt"
        try:
            resp = await self._client.get(url)
        except httpx.HTTPError as exc:
            log.warning(
                "robots.txt non raggiungibile per %s (%s: %s): consento",
                host, exc.__class__.__name__, exc,
            )
            return None
        if resp.status_code >= 500:
            log.warning("robots.txt %s ha risposto %s: consento", host, resp.status_code)
            return None
        if resp.status_code >= 400:
            return None  # nessun robots.txt: tutto consentito
        parser = RobotFileParser()
        parser.parse(resp.text.splitlines())
        return parser

    async def can_fetch(self, url: str) -> bool:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if not host:
            return False
        entry = self._cache.get(host)
        now = time.monotonic()
        if entry is None or now - entry[0] > self._ttl:
            parser = await self._load(parts.scheme or "https", host)
            self._cache[host] = (now, parser)
        else:
            parser = entry[1]
        if parser is None:
            return True
        return parser.can_fetch(self._user_agent, url)

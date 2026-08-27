"""Rate limit per dominio: cortesia di rete, max 1 richiesta ogni N secondi.

Il limite di default (2 s) vale per i siti delle testate; per servizi che
chiedono più prudenza (GDELT) si usano intervalli maggiori via `overrides`.
"""

import asyncio
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable

from core.config import get_settings

# GDELT chiede esplicitamente di non superare ~1 richiesta ogni 5 secondi.
DEFAULT_OVERRIDES: dict[str, float] = {"api.gdeltproject.org": 5.0}


class DomainRateLimiter:
    def __init__(
        self,
        min_interval: float | None = None,
        overrides: dict[str, float] | None = None,
        *,
        now: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.min_interval = (
            min_interval if min_interval is not None else get_settings().rate_limit_seconds
        )
        self.overrides = DEFAULT_OVERRIDES | (overrides or {})
        self._now = now
        self._sleep = sleep
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._last: dict[str, float] = {}

    def _interval_for(self, host: str) -> float:
        return self.overrides.get(host, self.min_interval)

    async def wait(self, host: str) -> None:
        """Blocca finché non è passato l'intervallo minimo per questo host."""
        host = host.lower()
        async with self._locks[host]:
            last = self._last.get(host)
            if last is not None:
                elapsed = self._now() - last
                remaining = self._interval_for(host) - elapsed
                if remaining > 0:
                    await self._sleep(remaining)
            self._last[host] = self._now()

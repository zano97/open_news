"""Fase 1: rate limit per dominio con orologio finto (nessuna attesa reale)."""

from core.ingest.ratelimit import DomainRateLimiter


class FakeClock:
    def __init__(self) -> None:
        self.time = 0.0
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.time

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.time += seconds


async def test_seconda_richiesta_stesso_host_attende() -> None:
    clock = FakeClock()
    limiter = DomainRateLimiter(min_interval=2.0, now=clock.now, sleep=clock.sleep)
    await limiter.wait("esempio.test")
    clock.time += 0.5  # è passato mezzo secondo
    await limiter.wait("esempio.test")
    assert clock.sleeps == [1.5]


async def test_host_diversi_non_si_bloccano(self_interval: float = 2.0) -> None:
    clock = FakeClock()
    limiter = DomainRateLimiter(min_interval=self_interval, now=clock.now, sleep=clock.sleep)
    await limiter.wait("uno.test")
    await limiter.wait("due.test")
    assert clock.sleeps == []


async def test_intervallo_gia_trascorso_non_attende() -> None:
    clock = FakeClock()
    limiter = DomainRateLimiter(min_interval=2.0, now=clock.now, sleep=clock.sleep)
    await limiter.wait("esempio.test")
    clock.time += 3.0
    await limiter.wait("esempio.test")
    assert clock.sleeps == []


async def test_override_gdelt_piu_prudente() -> None:
    clock = FakeClock()
    limiter = DomainRateLimiter(min_interval=2.0, now=clock.now, sleep=clock.sleep)
    await limiter.wait("api.gdeltproject.org")
    await limiter.wait("api.gdeltproject.org")
    assert clock.sleeps == [5.0]

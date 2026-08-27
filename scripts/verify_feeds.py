"""Verifica via HTTP reale i feed di data/sources.yaml e aggiorna il catalogo.

Da eseguire al setup e periodicamente (`make verify-feeds`). Per ogni fonte:
- interroga ogni feed con il client con guardia egress e rate limit;
- scrive nel catalogo `last_checked` e, se NESSUN feed risponde con contenuto
  interpretabile, `enabled: false` con `disabled_reason` automatico;
- una fonte disabilitata automaticamente viene riabilitata se torna a
  rispondere; le disabilitazioni di policy (es. ANSA) non vengono mai toccate.

Il file YAML è riscritto preservando i commenti (ruamel.yaml).
"""

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from ruamel.yaml import YAML

from core.ingest.catalog import CATALOG_PATH
from core.ingest.ratelimit import DomainRateLimiter
from core.ingest.rss import parse_feed
from core.net import build_client

AUTO_REASON_PREFIX = "verifica automatica:"


async def check_feed(
    client: httpx.AsyncClient, limiter: DomainRateLimiter, url: str
) -> tuple[bool, str]:
    host = urlsplit(url).hostname or ""
    await limiter.wait(host)
    try:
        resp = await client.get(url)
    except httpx.HTTPError as exc:
        return False, f"errore di rete: {exc.__class__.__name__}"
    if resp.status_code != 200:
        return False, f"HTTP {resp.status_code}"
    entries = parse_feed(resp.content)
    if not entries:
        return False, "feed vuoto o non interpretabile"
    return True, f"ok ({len(entries)} voci)"


async def verify(path: Path = CATALOG_PATH) -> int:
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 100
    data = yaml.load(path.read_text(encoding="utf-8"))

    failures = 0
    async with build_client() as client:
        limiter = DomainRateLimiter()
        for src in data["sources"]:
            feeds = src.get("feed_urls") or []
            if not feeds:
                print(f"— {src['slug']}: nessun feed (copertura via GDELT)")
                continue
            reason = src.get("disabled_reason") or ""
            policy_disabled = not src.get("enabled", True) and not reason.startswith(
                AUTO_REASON_PREFIX
            )
            results = []
            for url in feeds:
                ok, detail = await check_feed(client, limiter, url)
                results.append((url, ok, detail))
                stato = "OK " if ok else "ERR"
                print(f"{stato} {src['slug']}: {url} — {detail}")
            src["last_checked"] = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
            if policy_disabled:
                continue  # mai riabilitare disabilitazioni di policy
            if any(ok for _, ok, _ in results):
                if reason.startswith(AUTO_REASON_PREFIX):
                    src["disabled_reason"] = None
                src["enabled"] = True
            else:
                src["enabled"] = False
                dettagli = "; ".join(f"{u}: {d}" for u, _, d in results)
                src["disabled_reason"] = f"{AUTO_REASON_PREFIX} {dettagli}"
                failures += 1

    with path.open("w", encoding="utf-8") as fh:
        yaml.dump(data, fh)
    print(f"\nCatalogo aggiornato: {path} — fonti disabilitate automaticamente: {failures}")
    return failures


def main() -> None:
    failures = asyncio.run(verify())
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()

"""Riscarica i font self-hosted (già committati) dal repo google/fonts.

Serve solo per aggiornarli: il sito funziona senza rete perché i file sono
nel repository con le rispettive licenze (OFL 1.1; Special Elite: Apache 2.0).
"""

import asyncio
from pathlib import Path

from core.net import build_client

FONTS_DIR = Path(__file__).resolve().parent.parent / "apps" / "web" / "static" / "fonts"
BASE = "https://raw.githubusercontent.com/google/fonts/main"

FILES = {
    "PlayfairDisplay-Variable.ttf": f"{BASE}/ofl/playfairdisplay/PlayfairDisplay%5Bwght%5D.ttf",
    "OFL-PlayfairDisplay.txt": f"{BASE}/ofl/playfairdisplay/OFL.txt",
    "EBGaramond-Variable.ttf": f"{BASE}/ofl/ebgaramond/EBGaramond%5Bwght%5D.ttf",
    "EBGaramond-Italic-Variable.ttf": f"{BASE}/ofl/ebgaramond/EBGaramond-Italic%5Bwght%5D.ttf",
    "OFL-EBGaramond.txt": f"{BASE}/ofl/ebgaramond/OFL.txt",
    "SpecialElite-Regular.ttf": f"{BASE}/apache/specialelite/SpecialElite-Regular.ttf",
    "LICENSE-SpecialElite.txt": f"{BASE}/apache/specialelite/LICENSE.txt",
}


async def main_async() -> None:
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    async with build_client(timeout=60) as client:
        for name, url in FILES.items():
            resp = await client.get(url)
            resp.raise_for_status()
            (FONTS_DIR / name).write_bytes(resp.content)
            print(f"scaricato {name} ({len(resp.content)} byte)")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()

"""Definizione di fatto: nessuna chiamata verso servizi fuori allowlist.

Due difese, entrambe testate:
1. runtime: ogni client HTTP passa da core.net.build_client, che rifiuta gli
   host fuori allowlist (vedi tests/test_net.py);
2. statica (questo file): nel codice di produzione non si costruiscono client
   httpx "nudi" che aggirerebbero la guardia.
"""

from pathlib import Path

BASE = Path(__file__).resolve().parent.parent


def _python_files(*roots: str) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        files.extend((BASE / root).rglob("*.py"))
    return files


def test_client_httpx_solo_in_core_net() -> None:
    """`httpx.AsyncClient(` è ammesso solo in core/net.py (e nei test)."""
    violazioni = []
    for path in _python_files("core", "apps", "scripts"):
        if path == BASE / "core" / "net.py":
            continue
        if "httpx.AsyncClient(" in path.read_text(encoding="utf-8"):
            violazioni.append(str(path.relative_to(BASE)))
    assert not violazioni, (
        "client httpx costruiti fuori da core.net.build_client "
        f"(aggirano l'allowlist): {violazioni}"
    )


def test_nessun_sdk_di_servizi_a_pagamento() -> None:
    """Nessun import di SDK di servizi commerciali nel codice di produzione."""
    vietati = ("import openai", "from openai", "import anthropic", "from anthropic",
               "newsapi", "import stripe", "gnews")
    violazioni = []
    for path in _python_files("core", "apps", "scripts"):
        contenuto = path.read_text(encoding="utf-8").lower()
        for marker in vietati:
            if marker in contenuto:
                violazioni.append(f"{path.relative_to(BASE)}: {marker}")
    assert not violazioni, violazioni

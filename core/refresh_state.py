"""Stato condiviso dei cicli di raccolta: chi sta lavorando, com'è andata.

Serve a due cose visibili:
- la barra di caricamento in testata (compare quando QUALSIASI ciclo di
  aggiornamento è in corso, automatico o su richiesta);
- la sezione Diagnostica di /impostazioni, che mostra l'ultimo esito di
  ogni ciclo — "sta aggiornando o no?" ha sempre una risposta.
"""

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

_active: dict[str, int] = {}
LAST_RUNS: dict[str, dict[str, str]] = {}


def is_running() -> bool:
    return any(n > 0 for n in _active.values())


@asynccontextmanager
async def tracking(kind: str) -> AsyncIterator[None]:
    """Avvolge un ciclo di lavoro: attivo mentre gira, esito registrato."""
    _active[kind] = _active.get(kind, 0) + 1
    start = time.monotonic()
    esito = "ok"
    try:
        yield
    except Exception:
        esito = "errore"
        raise
    finally:
        _active[kind] = max(0, _active.get(kind, 1) - 1)
        LAST_RUNS[kind] = {
            "quando": datetime.now(UTC).strftime("%H:%M:%S UTC"),
            "esito": esito,
            "durata": f"{time.monotonic() - start:.0f}s",
        }

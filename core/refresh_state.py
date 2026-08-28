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

# Avanzamento del ciclo attivo: (fatti, totale) per tipo. Il totale è noto
# (numero di feed, di gruppi GDELT, ...) quindi la percentuale è VERA.
_progress: dict[str, tuple[int, int]] = {}

# Giro manuale («Aggiorna ora»): tre fasi con pesi, per una sola barra che
# avanza da 0 a 100 senza tornare indietro tra una fase e l'altra.
_MANUAL_WEIGHTS: dict[str, float] = {"feed": 0.55, "GDELT": 0.35, "clustering": 0.10}
_manual_done: set[str] | None = None


def is_running() -> bool:
    return any(n > 0 for n in _active.values())


def set_progress(kind: str, done: int, total: int) -> None:
    _progress[kind] = (done, max(total, 1))


def begin_manual() -> None:
    global _manual_done
    _manual_done = set()


def end_manual() -> None:
    global _manual_done
    _manual_done = None


def _fraction(kind: str) -> float:
    done, total = _progress.get(kind, (0, 1))
    return min(done / total, 1.0)


def overall() -> tuple[int | None, str | None]:
    """(percentuale 0-100, fase attiva) — o (None, fase) se non stimabile."""
    attivi = [k for k, n in _active.items() if n > 0]
    if _manual_done is not None:
        base = sum(_MANUAL_WEIGHTS.get(k, 0.0) for k in _manual_done)
        fase = next((k for k in attivi if k in _MANUAL_WEIGHTS), None)
        if fase is not None:
            base += _MANUAL_WEIGHTS[fase] * _fraction(fase)
        return min(int(base * 100), 99), fase
    if not attivi:
        return None, None
    fase = attivi[0]
    if fase in _progress:
        return min(int(_fraction(fase) * 100), 99), fase
    return None, fase


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
        _progress.pop(kind, None)
        if _manual_done is not None:
            _manual_done.add(kind)
        LAST_RUNS[kind] = {
            "quando": datetime.now(UTC).strftime("%H:%M:%S UTC"),
            "esito": esito,
            "durata": f"{time.monotonic() - start:.0f}s",
        }

"""Registro degli eventi in memoria, visibile dal pannello /impostazioni.

Un utente non deve aprire un terminale per capire perché qualcosa non va:
gli ultimi eventi di log (raccolta, generatore, errori) restano in un ring
buffer e il pannello di amministrazione li mostra. In modalità personale il
launcher scrive anche su file (~/.opennews/opennews.log); in modalità
server Docker questo buffer riguarda il processo web — per il raccoglitore:
`docker compose logs worker`.
"""

import logging
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime

MAX_RECORDS = 400


@dataclass(frozen=True)
class LogEntry:
    when: datetime
    level: str
    levelno: int
    logger: str
    message: str


class RingBufferHandler(logging.Handler):
    def __init__(self, maxlen: int = MAX_RECORDS) -> None:
        super().__init__(level=logging.INFO)
        self.entries: deque[LogEntry] = deque(maxlen=maxlen)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)
        self.entries.append(
            LogEntry(
                when=datetime.fromtimestamp(record.created, tz=UTC),
                level=record.levelname,
                levelno=record.levelno,
                logger=record.name,
                message=message,
            )
        )


_handler: RingBufferHandler | None = None


def install() -> RingBufferHandler:
    """Aggancia (una sola volta) il buffer al logger radice."""
    global _handler
    if _handler is None:
        _handler = RingBufferHandler()
        root = logging.getLogger()
        root.addHandler(_handler)
        if root.level > logging.INFO or root.level == logging.NOTSET:
            root.setLevel(logging.INFO)
    return _handler


def recent(limit: int = 80, *, min_level: int = logging.WARNING) -> list[LogEntry]:
    """Gli eventi più recenti (i più nuovi per primi), dal livello indicato."""
    if _handler is None:
        return []
    scelti = [e for e in _handler.entries if e.levelno >= min_level]
    return list(reversed(scelti))[:limit]

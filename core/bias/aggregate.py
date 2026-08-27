"""Orchestrazione del calcolo settimanale dei segnali (livelli 2 e 3).

Idempotente: i segnali dello stesso periodo vengono sostituiti, quelli dei
periodi precedenti restano come storico datato (metodologia §5: le etichette
sono ricalcolate ogni settimana e datate).
"""

import logging
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from core.bias.framing import compute_actors, compute_framing, compute_tone
from core.bias.selection import (
    assign_story_topics,
    compute_agenda,
    compute_blindspots,
    store_cocoverage,
)
from core.config import get_settings
from core.models import utcnow

log = logging.getLogger(__name__)


async def compute_weekly_signals(
    session: AsyncSession, *, window_days: int | None = None
) -> dict[str, int]:
    window = window_days or get_settings().signal_window_days
    since = utcnow() - timedelta(days=window)
    summary = {
        "story_topics": await assign_story_topics(session, since),
        "agenda": await compute_agenda(session, window_days=window),
        "cocoverage": await store_cocoverage(session, window_days=window),
        "blindspot": await compute_blindspots(session, window_days=window),
        "framing": await compute_framing(session, window_days=window),
        "actors": await compute_actors(session, window_days=window),
        "tone": await compute_tone(session, window_days=window),
    }
    log.info("segnali settimanali: %s", summary)
    return summary

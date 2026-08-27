"""Scrittura idempotente dei segnali di bias, sempre con provenance."""

from datetime import date
from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import BiasSignal
from core.provenance import record


async def write_signal(
    session: AsyncSession,
    *,
    source_id: int,
    signal_type: str,
    period_start: date,
    period_end: date,
    value: Any,
    n_articles: int,
    method: str,
    axis: str | None = None,
    ci_low: float | None = None,
    ci_high: float | None = None,
    inputs: dict[str, Any] | None = None,
) -> BiasSignal:
    """Sostituisce l'eventuale segnale identico (stessa fonte/tipo/asse/periodo)."""
    await session.execute(
        delete(BiasSignal).where(
            BiasSignal.source_id == source_id,
            BiasSignal.signal_type == signal_type,
            BiasSignal.axis == axis,
            BiasSignal.period_start == period_start,
            BiasSignal.period_end == period_end,
        )
    )
    signal = BiasSignal(
        source_id=source_id,
        signal_type=signal_type,
        axis=axis,
        period_start=period_start,
        period_end=period_end,
        value=value,
        n_articles=n_articles,
        ci_low=ci_low,
        ci_high=ci_high,
        method_version=_method_version(),
    )
    session.add(signal)
    await session.flush()
    await record(
        session,
        entity_type="bias_signal",
        entity_id=signal.id,
        field=signal_type,
        method=method,
        inputs={
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "n_articles": n_articles,
            **(inputs or {}),
        },
    )
    return signal


def _method_version() -> str:
    from core.config import METHOD_VERSION

    return METHOD_VERSION

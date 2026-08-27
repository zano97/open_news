"""Segnali di bias per fonte e periodo (livelli 2 e 3 della metodologia).

`value` è JSON perché la forma dipende dal segnale: un vettore di scostamenti
per l'agenda, coordinate {x, y} per la co-copertura, frequenze per gruppo per
il framing. Il significato esatto è documentato in docs/METHODOLOGY.md ed è
individuato da (signal_type, method_version).
"""

from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base, utcnow
from core.models.types import JSONVariant, TZDateTime


class BiasSignal(Base):
    __tablename__ = "bias_signals"
    __table_args__ = (
        Index("ix_bias_signals_lookup", "source_id", "signal_type", "period_end"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    # agenda | cocoverage | blindspot | framing | actors | tone | annotation
    signal_type: Mapped[str] = mapped_column(String(20))
    axis: Mapped[str | None] = mapped_column(String(20))  # economic | cultural | None
    value: Mapped[Any] = mapped_column(JSONVariant)
    ci_low: Mapped[float | None] = mapped_column(Float)
    ci_high: Mapped[float | None] = mapped_column(Float)
    n_articles: Mapped[int] = mapped_column(Integer, default=0)
    method_version: Mapped[str] = mapped_column(String(20))
    computed_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)

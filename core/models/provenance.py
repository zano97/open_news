"""Provenance: ogni valore derivato sa da dove viene.

Regola del progetto: nessun numero o etichetta compare nell'interfaccia senza
un record Provenance che indichi metodo, versione, input e momento del calcolo.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base, utcnow
from core.models.types import JSONVariant, TZDateTime


class Provenance(Base):
    __tablename__ = "provenances"
    __table_args__ = (
        Index("ix_provenances_entity", "entity_type", "entity_id", "field"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(40))  # es. "story", "source", "bias_signal"
    entity_id: Mapped[int] = mapped_column(Integer)
    field: Mapped[str] = mapped_column(String(60))  # es. "topic", "agenda", "ownership"
    method: Mapped[str] = mapped_column(String(120))  # es. "keyword-taxonomy"
    method_version: Mapped[str] = mapped_column(String(20))
    # Input essenziali per riprodurre il calcolo (id, parametri, finestre temporali).
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONVariant, default=dict)
    source_name: Mapped[str | None] = mapped_column(String(200))  # per dati importati
    source_url: Mapped[str | None] = mapped_column(Text)
    computed_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)

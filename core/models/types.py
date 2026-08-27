"""Tipi di colonna portabili tra PostgreSQL (produzione) e SQLite (test)."""

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator, TypeEngine

JSONVariant = JSON().with_variant(JSONB(), "postgresql")
"""JSON normale su SQLite, JSONB su PostgreSQL."""


class TZDateTime(TypeDecorator[datetime]):
    """Datetime sempre timezone-aware UTC, anche su SQLite (che perde il fuso)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("i datetime devono essere timezone-aware (UTC)")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class EmbeddingVector(TypeDecorator[list[float]]):
    """`vector(dim)` di pgvector su PostgreSQL; JSON testuale su SQLite.

    La KNN nativa (`<=>`) esiste solo su PostgreSQL; su SQLite la similarità
    è calcolata in Python (vedi core/cluster/knn.py) — adeguato ai test.
    """

    impl = Text
    cache_ok = True

    def __init__(self, dim: int = 768) -> None:
        super().__init__()
        self.dim = dim

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector

            return dialect.type_descriptor(Vector(self.dim))
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value: list[float] | None, dialect: Dialect) -> Any:
        if value is None:
            return None
        if len(value) != self.dim:
            raise ValueError(f"embedding di dimensione {len(value)}, attesa {self.dim}")
        if dialect.name == "postgresql":
            return value
        return json.dumps([round(float(x), 8) for x in value])

    def process_result_value(self, value: Any, dialect: Dialect) -> list[float] | None:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return [float(x) for x in value]
        loaded = json.loads(value)
        return [float(x) for x in loaded]

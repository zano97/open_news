"""Registrazione e lettura della provenance dei valori derivati."""

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import METHOD_VERSION
from core.models import Provenance


async def record(
    session: AsyncSession,
    *,
    entity_type: str,
    entity_id: int,
    field: str,
    method: str,
    inputs: dict[str, Any] | None = None,
    source_name: str | None = None,
    source_url: str | None = None,
    method_version: str = METHOD_VERSION,
) -> Provenance:
    """Scrive (sostituendo l'eventuale precedente) la provenance di un valore.

    Idempotente per (entity_type, entity_id, field, method): un ricalcolo
    sostituisce il record, così l'interfaccia mostra sempre l'ultimo calcolo.
    """
    await session.execute(
        delete(Provenance).where(
            Provenance.entity_type == entity_type,
            Provenance.entity_id == entity_id,
            Provenance.field == field,
            Provenance.method == method,
        )
    )
    row = Provenance(
        entity_type=entity_type,
        entity_id=entity_id,
        field=field,
        method=method,
        method_version=method_version,
        inputs=inputs or {},
        source_name=source_name,
        source_url=source_url,
    )
    session.add(row)
    await session.flush()
    return row


async def for_entity(
    session: AsyncSession, entity_type: str, entity_id: int
) -> list[Provenance]:
    result = await session.execute(
        select(Provenance)
        .where(Provenance.entity_type == entity_type, Provenance.entity_id == entity_id)
        .order_by(Provenance.field, Provenance.computed_at.desc())
    )
    return list(result.scalars())

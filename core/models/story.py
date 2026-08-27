"""Story (cluster di articoli sullo stesso evento) e relativa mappa di copertura."""

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.config import get_settings
from core.models.article import Article
from core.models.base import Base, utcnow
from core.models.types import EmbeddingVector, JSONVariant, TZDateTime


class Story(Base):
    __tablename__ = "stories"
    __table_args__ = (
        Index("ix_stories_last_seen", "last_seen"),
        Index("ix_stories_is_flash", "is_flash"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title_neutral: Mapped[str] = mapped_column(Text)
    # Metodo con cui è stato scelto il titolo neutro: "centroide" oppure "llm".
    title_method: Mapped[str] = mapped_column(String(20), default="centroide")
    summary_neutral: Mapped[str | None] = mapped_column(Text)
    summary_method: Mapped[str | None] = mapped_column(String(20))  # solo "llm", sempre marcato
    first_seen: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    entities: Mapped[list[dict[str, Any]]] = mapped_column(JSONVariant, default=list)
    article_count: Mapped[int] = mapped_column(Integer, default=0)
    source_count: Mapped[int] = mapped_column(Integer, default=0)
    is_flash: Mapped[bool] = mapped_column(Boolean, default=False)
    topic: Mapped[str | None] = mapped_column(String(40), index=True)
    # [{"id": str, "score": float}] — punteggi della classificazione a tassonomia fissa.
    topics: Mapped[list[dict[str, Any]]] = mapped_column(JSONVariant, default=list)
    centroid: Mapped[list[float] | None] = mapped_column(
        EmbeddingVector(get_settings().embedding_dim)
    )

    articles: Mapped[list[Article]] = relationship(
        lazy="selectin", order_by=Article.published_at
    )


class Coverage(Base):
    __tablename__ = "coverages"

    id: Mapped[int] = mapped_column(primary_key=True)
    story_id: Mapped[int] = mapped_column(ForeignKey("stories.id"), unique=True, index=True)
    by_country: Mapped[dict[str, int]] = mapped_column(JSONVariant, default=dict)
    by_language: Mapped[dict[str, int]] = mapped_column(JSONVariant, default=dict)
    # Conteggio fonti per fascia di ciascun asse del livello 4 (solo se pubblicato):
    # {"economic": {"-2..-1": n, ...}, "cultural": {...}}
    by_axis: Mapped[dict[str, Any]] = mapped_column(JSONVariant, default=dict)
    # [{"group": str, "kind": "country"|"axis", "threshold": float, "detail": str}]
    blindspot_for: Mapped[list[dict[str, Any]]] = mapped_column(JSONVariant, default=list)
    method_version: Mapped[str] = mapped_column(String(20))
    computed_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)

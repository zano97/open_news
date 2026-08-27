"""Articoli raccolti dai feed.

Legalità: via API/UI escono solo titolo, snippet (max ~200 caratteri), immagine
di anteprima e link. `full_text` è una colonna interna usata per l'analisi
locale e non è mai serializzata (vedi apps/api/schemas.py e docs/LEGAL.md).
"""

from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.config import get_settings
from core.models.base import Base, utcnow
from core.models.source import Source
from core.models.types import EmbeddingVector, JSONVariant, TZDateTime

SNIPPET_MAX_CHARS = 200


class Article(Base):
    __tablename__ = "articles"
    __table_args__ = (
        Index("ix_articles_published_at", "published_at"),
        Index("ix_articles_story_id", "story_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    url: Mapped[str] = mapped_column(Text, unique=True)
    canonical_url: Mapped[str | None] = mapped_column(Text, index=True)
    title: Mapped[str] = mapped_column(Text)
    snippet: Mapped[str] = mapped_column(String(SNIPPET_MAX_CHARS + 20), default="")
    image_url: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    fetched_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    language: Mapped[str | None] = mapped_column(String(8))
    authors: Mapped[list[str]] = mapped_column(JSONVariant, default=list)
    # Interna: mai esposta via API né UI. Serve solo all'analisi locale.
    full_text: Mapped[str | None] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(
        EmbeddingVector(get_settings().embedding_dim)
    )
    embedding_method: Mapped[str | None] = mapped_column(String(40))
    # [{"qid": str|None, "label": str, "type": str}]
    entities: Mapped[list[dict[str, Any]]] = mapped_column(JSONVariant, default=list)
    simhash: Mapped[str | None] = mapped_column(String(16), index=True)  # 64 bit in esadecimale
    story_id: Mapped[int | None] = mapped_column(ForeignKey("stories.id"))

    source: Mapped[Source] = relationship()

"""Livello 4: annotazione umana cieca con protocollo dichiarato.

L'annotatore dichiara il proprio orientamento sui due assi; il dato serve a
verificare che le etichette pubblicate nascano dall'accordo tra annotatori con
orientamenti diversi (vedi core/bias/annotation.py e docs/METHODOLOGY.md §4).
"""

from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base, utcnow
from core.models.types import TZDateTime


class AnnotatorProfile(Base):
    __tablename__ = "annotators"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    display_name: Mapped[str] = mapped_column(String(120), default="")
    # Auto-dichiarazione sui due assi, scala -2..+2 (vedi metodologia §4).
    self_axis_economic: Mapped[float] = mapped_column(Float, default=0.0)
    self_axis_cultural: Mapped[float] = mapped_column(Float, default=0.0)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)


class Annotation(Base):
    __tablename__ = "annotations"
    __table_args__ = (
        UniqueConstraint(
            "article_id", "annotator_id", "axis", name="uq_annotation_article_annotator_axis"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id"), index=True)
    annotator_id: Mapped[int] = mapped_column(ForeignKey("annotators.id"), index=True)
    axis: Mapped[str] = mapped_column(String(20))  # economic | cultural
    # -2..+2; None se l'annotatore ha scelto "non applicabile".
    value: Mapped[int | None] = mapped_column(Integer)
    not_applicable: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence: Mapped[int] = mapped_column(Integer, default=2)  # 1 = bassa, 3 = alta
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)

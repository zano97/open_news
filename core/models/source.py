"""Fonti (testate), proprietari e finanziamenti: il livello 1 della metodologia.

Qui vivono solo fatti verificabili: ogni riga di Ownership e PublicFunding
porta con sé nome dell'evidenza, URL e data di rilevamento. Nessuna etichetta
di orientamento importata da terzi.
"""

from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.models.base import Base, utcnow
from core.models.types import JSONVariant, TZDateTime


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    domain: Mapped[str] = mapped_column(String(200), index=True)
    country: Mapped[str] = mapped_column(String(2), index=True)
    language: Mapped[str] = mapped_column(String(8))
    region: Mapped[str] = mapped_column(String(20), default="world")  # italy | europe | world
    feed_urls: Mapped[list[str]] = mapped_column(JSONVariant, default=list)
    gdelt_domain: Mapped[str | None] = mapped_column(String(200))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    disabled_reason: Mapped[str | None] = mapped_column(Text)
    terms_note: Mapped[str] = mapped_column(Text, default="")
    wikidata_qid: Mapped[str | None] = mapped_column(String(20))
    founded: Mapped[int | None] = mapped_column(Integer)
    # {"quote": str, "url": str} — citazione testuale della linea auto-dichiarata.
    self_declared_line: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant)
    # Segnali pubblici raccolti dalla testata stessa e da archivi liberi
    # (core/osint/): ads.txt, impegni di trasparenza dichiarati in
    # schema.org, prima copia archiviata. Sempre con provenance.
    osint: Mapped[dict[str, Any]] = mapped_column(JSONVariant, default=dict)
    last_checked_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)

    ownerships: Mapped[list["Ownership"]] = relationship(back_populates="source")
    fundings: Mapped[list["PublicFunding"]] = relationship(back_populates="source")


class FeedState(Base):
    """Stato per-feed della cache HTTP condizionale (ETag / Last-Modified)."""

    __tablename__ = "feed_states"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    feed_url: Mapped[str] = mapped_column(Text, unique=True)
    etag: Mapped[str | None] = mapped_column(String(300))
    last_modified: Mapped[str | None] = mapped_column(String(100))
    last_status: Mapped[int | None] = mapped_column(Integer)
    last_fetched_at: Mapped[datetime | None] = mapped_column(TZDateTime())
    error: Mapped[str | None] = mapped_column(Text)
    # Se l'URL del catalogo è morto ma il sito espone un feed alternativo
    # (autodiscovery da <link rel="alternate">), qui resta l'URL trovato.
    resolved_url: Mapped[str | None] = mapped_column(Text)
    # Errori consecutivi: oltre la soglia il feed viene riprovato con calma.
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )


class Owner(Base):
    __tablename__ = "owners"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    # persona | società | fondazione | partito | stato | cooperativa
    type: Mapped[str] = mapped_column(String(20))
    wikidata_qid: Mapped[str | None] = mapped_column(String(20))
    # [{"office": str, "holder_note": str, "from_year": int|None,
    #   "to_year": int|None, "evidence_url": str}]
    political_offices: Mapped[list[dict[str, Any]]] = mapped_column(JSONVariant, default=list)
    # Fatti raccolti da Wikidata (CC0) per il proprietario con QID confermato:
    # {"facts": [{"meaning", "label", "qid", "start", "end"}], "retrieved_at": iso}
    # Mostrati sempre come "secondo Wikidata", mai come valutazioni nostre.
    details: Mapped[dict[str, Any]] = mapped_column(JSONVariant, default=dict)
    source_url: Mapped[str | None] = mapped_column(Text)
    retrieved_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)

    ownerships: Mapped[list["Ownership"]] = relationship(back_populates="owner")


class Ownership(Base):
    __tablename__ = "ownerships"
    __table_args__ = (UniqueConstraint("source_id", "owner_id", name="uq_ownership_source_owner"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("owners.id"), index=True)
    share_pct: Mapped[float | None] = mapped_column(Float)
    from_date: Mapped[date | None] = mapped_column(Date)
    to_date: Mapped[date | None] = mapped_column(Date)
    evidence_name: Mapped[str] = mapped_column(String(120))  # es. "ROC AGCOM", "Wikidata"
    evidence_url: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)

    source: Mapped[Source] = relationship(back_populates="ownerships")
    owner: Mapped[Owner] = relationship(back_populates="ownerships")


class PublicFunding(Base):
    __tablename__ = "public_fundings"
    __table_args__ = (
        UniqueConstraint("source_id", "year", "program", name="uq_funding_source_year_program"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    year: Mapped[int] = mapped_column(Integer)
    amount_eur: Mapped[float | None] = mapped_column(Float)
    program: Mapped[str] = mapped_column(Text)
    evidence_url: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)

    source: Mapped[Source] = relationship(back_populates="fundings")

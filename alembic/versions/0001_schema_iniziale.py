"""Schema iniziale: estensione pgvector + tutte le tabelle dai modelli.

La migrazione 0001 crea lo schema direttamente dai metadati dei modelli
(un'unica fonte di verità allo stato iniziale); le migrazioni successive
saranno incrementali. Vedi docs/DECISIONS.md (ADR-0004).

Revision ID: 0001
Revises:
Create Date: 2026-08-27

"""
from collections.abc import Sequence

from alembic import op

from core.models import Base

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    Base.metadata.create_all(bind)
    if bind.dialect.name == "postgresql":
        # Indice ANN per la KNN sugli embedding degli articoli (cosine).
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_articles_embedding_hnsw "
            "ON articles USING hnsw (embedding vector_cosine_ops)"
        )


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind)

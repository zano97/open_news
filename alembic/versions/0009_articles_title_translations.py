"""Colonna articles.title_translations: traduzioni dei titoli delle versioni.

Solo un AIUTO DI LETTURA: il titolo originale resta il dato misurato
(framing) e in pagina è sempre protagonista; la traduzione compare sotto,
marcata come automatica. Cache per lingua con la stessa semantica delle
story (stringa vuota = tentata, uscita identica: non si ritenta).

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-30

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {c["name"] for c in sa.inspect(bind).get_columns("articles")}
    if "title_translations" in columns:
        return
    op.add_column(
        "articles",
        sa.Column(
            "title_translations",
            sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql"),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    op.drop_column("articles", "title_translations")

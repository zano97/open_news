"""Colonna stories.title_translations (traduzioni automatiche dei titoli neutri).

I DB nuovi la ricevono dalla 0001 (create_all): qui si aggiunge solo se manca.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-27

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {c["name"] for c in sa.inspect(bind).get_columns("stories")}
    if "title_translations" in columns:
        return
    op.add_column(
        "stories",
        sa.Column(
            "title_translations",
            sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql"),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    op.drop_column("stories", "title_translations")

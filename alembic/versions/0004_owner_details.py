"""Colonna owners.details (fatti Wikidata sui proprietari).

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-27

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {c["name"] for c in sa.inspect(bind).get_columns("owners")}
    if "details" in columns:
        return
    op.add_column(
        "owners",
        sa.Column(
            "details",
            sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql"),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    op.drop_column("owners", "details")

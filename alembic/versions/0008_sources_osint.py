"""Colonna sources.osint: segnali pubblici raccolti sulle testate.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-28

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {c["name"] for c in sa.inspect(bind).get_columns("sources")}
    if "osint" in columns:
        return
    op.add_column(
        "sources",
        sa.Column(
            "osint",
            sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql"),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    op.drop_column("sources", "osint")

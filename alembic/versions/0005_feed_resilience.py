"""Colonne feed_states.resolved_url e consecutive_failures (feed che si auto-riparano).

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-27

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {c["name"] for c in sa.inspect(bind).get_columns("feed_states")}
    if "resolved_url" not in columns:
        op.add_column("feed_states", sa.Column("resolved_url", sa.Text(), nullable=True))
    if "consecutive_failures" not in columns:
        op.add_column(
            "feed_states",
            sa.Column(
                "consecutive_failures",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )


def downgrade() -> None:
    op.drop_column("feed_states", "consecutive_failures")
    op.drop_column("feed_states", "resolved_url")

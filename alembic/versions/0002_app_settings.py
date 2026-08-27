"""Tabella app_settings per le impostazioni di runtime (pannello admin).

I DB nuovi la ricevono già dalla 0001 (create_all dai metadati): qui si crea
solo se manca, per aggiornare le installazioni esistenti.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-27

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("app_settings"):
        return
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(60), primary_key=True),
        sa.Column("value", sa.String(500), nullable=False),
        sa.Column("updated_by", sa.String(120), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("app_settings")

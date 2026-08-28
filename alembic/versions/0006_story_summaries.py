"""Colonna stories.summaries (riassunti per lingua dell'interfaccia).

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-28

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {c["name"] for c in sa.inspect(bind).get_columns("stories")}
    if "summaries" in columns:
        return
    op.add_column(
        "stories",
        sa.Column(
            "summaries",
            sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql"),
            nullable=False,
            server_default="{}",
        ),
    )
    # I riassunti già generati restano leggibili: migrano nel nuovo campo
    # sotto la lingua di allora (italiano, l'unica usata finora).
    op.execute(
        "UPDATE stories SET summaries = json_object('it', summary_neutral) "
        "WHERE summary_neutral IS NOT NULL"
        if bind.dialect.name == "sqlite"
        else "UPDATE stories SET summaries = jsonb_build_object('it', summary_neutral) "
        "WHERE summary_neutral IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("stories", "summaries")

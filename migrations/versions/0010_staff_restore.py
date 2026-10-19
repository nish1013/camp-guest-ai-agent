"""staff restore: messages stopped by a park, and the ones a restore queues again

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "messages", sa.Column("parked", sa.Boolean, nullable=False, server_default=sa.false())
    )
    op.add_column(
        "messages", sa.Column("restored", sa.Boolean, nullable=False, server_default=sa.false())
    )
    op.create_check_constraint(
        "ck_messages_parked", "messages", "NOT (parked AND (restored OR handled_at IS NULL))"
    )


def downgrade() -> None:
    op.drop_constraint("ck_messages_parked", "messages", type_="check")
    op.drop_column("messages", "restored")
    op.drop_column("messages", "parked")

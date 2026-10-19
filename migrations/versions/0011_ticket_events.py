"""ticket status outbox

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TICKET_STATES = "('open', 'in_progress', 'done', 'cancelled')"


def upgrade() -> None:
    op.create_table(
        "ticket_events",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("ticket_ref", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(f"status IN {TICKET_STATES}", name="ck_ticket_events_status"),
    )
    op.create_index("ix_tasks_ticket_ref", "tasks", ["ticket_ref"])


def downgrade() -> None:
    op.drop_index("ix_tasks_ticket_ref", "tasks")
    op.drop_table("ticket_events")

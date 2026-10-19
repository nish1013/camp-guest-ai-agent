"""demo ticket system: tickets keyed by case and step

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

URGENCY = "('urgent', 'normal', 'can_wait')"
TEAMS = "('maintenance', 'housekeeping')"
TICKET_STATES = "('open', 'in_progress', 'done', 'cancelled')"


def upgrade() -> None:
    op.create_table(
        "demo_tickets",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("case_id", sa.BigInteger, nullable=False),
        sa.Column("step_id", sa.Text, nullable=False),
        sa.Column("cabin", sa.Text, nullable=False),
        sa.Column("team", sa.Text, nullable=False),
        sa.Column("fault_type", sa.Text, nullable=False),
        sa.Column("urgency", sa.Text, nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("case_id", "step_id", name="uq_demo_tickets_case_step"),
        sa.CheckConstraint(f"team IN {TEAMS}", name="ck_demo_tickets_team"),
        sa.CheckConstraint(f"urgency IN {URGENCY}", name="ck_demo_tickets_urgency"),
        sa.CheckConstraint(f"status IN {TICKET_STATES}", name="ck_demo_tickets_status"),
    )


def downgrade() -> None:
    op.drop_table("demo_tickets")

"""triage: case status, tasks, audit entries

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

URGENCY = "('urgent', 'normal', 'can_wait')"


def upgrade() -> None:
    op.add_column("cases", sa.Column("state_reason", sa.Text))
    op.add_column(
        "cases", sa.Column("safety", sa.Boolean, nullable=False, server_default=sa.false())
    )
    op.add_column("cases", sa.Column("urgency", sa.Text, nullable=False, server_default="normal"))
    op.add_column(
        "cases", sa.Column("clarify_rounds", sa.Integer, nullable=False, server_default="0")
    )
    op.add_column("cases", sa.Column("held_at", sa.DateTime(timezone=True)))
    op.drop_constraint("ck_cases_state", "cases", type_="check")
    op.create_check_constraint("ck_cases_state", "cases", "state IN ('open', 'held', 'parked')")
    op.create_check_constraint(
        "ck_cases_state_reason",
        "cases",
        "(state = 'open' AND state_reason IS NULL)"
        " OR (state = 'held'"
        " AND state_reason IN ('emergency', 'money', 'llm_failed', 'clarify_limit'))"
        " OR (state = 'parked' AND state_reason IN ('spam'))",
    )
    op.create_check_constraint(
        "ck_cases_held_at", "cases", "(state = 'held') = (held_at IS NOT NULL)"
    )
    op.create_check_constraint("ck_cases_urgency", "cases", f"urgency IN {URGENCY}")
    op.create_check_constraint("ck_cases_clarify_rounds", "cases", "clarify_rounds >= 0")
    op.create_check_constraint(
        "ck_cases_safety", "cases", "NOT safety OR (urgency = 'urgent' AND state <> 'parked')"
    )

    op.create_table(
        "tasks",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("case_id", sa.BigInteger, sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("step_id", sa.Text, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("category", sa.Text),
        sa.Column("urgency", sa.Text, nullable=False),
        sa.Column("state", sa.Text, nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("case_id", "step_id", name="uq_tasks_case_step"),
        sa.CheckConstraint(
            "kind IN ('question', 'fault', 'table', 'money', 'emergency')", name="ck_tasks_kind"
        ),
        sa.CheckConstraint(f"urgency IN {URGENCY}", name="ck_tasks_urgency"),
        sa.CheckConstraint("state IN ('queued', 'awaiting_scope', 'held')", name="ck_tasks_state"),
    )
    op.create_table(
        "audit_entries",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("case_id", sa.BigInteger, sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("step", sa.Text, nullable=False),
        sa.Column("decision", sa.Text, nullable=False),
        sa.Column(
            "detail", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_audit_entries_case", "audit_entries", ["case_id", "id"])


def downgrade() -> None:
    op.drop_table("audit_entries")
    op.drop_table("tasks")
    for name in (
        "ck_cases_safety",
        "ck_cases_clarify_rounds",
        "ck_cases_urgency",
        "ck_cases_held_at",
        "ck_cases_state_reason",
        "ck_cases_state",
    ):
        op.drop_constraint(name, "cases", type_="check")
    op.create_check_constraint("ck_cases_state", "cases", "state IN ('open')")
    for column in ("held_at", "clarify_rounds", "urgency", "safety", "state_reason"):
        op.drop_column("cases", column)

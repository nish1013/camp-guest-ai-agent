"""fault tickets: reports, validation records, ticket refs on tasks

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FAULT_TYPES = (
    "('hot_water', 'heating', 'leak', 'electrics', 'appliance', 'cleaning', 'supplies', 'other')"
)
TICKET_STATES = "('open', 'in_progress', 'done', 'cancelled')"
TASK_STATES = (
    "('queued', 'awaiting_scope', 'held', 'done', 'awaiting_split', 'split_confirmed',"
    " 'awaiting_same', 'drafting', 'linking', 'ticketed')"
)
HELD_REASONS = (
    "('emergency', 'money', 'llm_failed', 'clarify_limit', 'fault_review', 'ticketing_down')"
)
OLD_HELD_REASONS = "('emergency', 'money', 'llm_failed', 'clarify_limit')"


def upgrade() -> None:
    _state_reason(HELD_REASONS)
    # The target of the I5 composite key: a task's cabin must be its case's scope cabin.
    op.create_unique_constraint("uq_cases_id_scope_cabin", "cases", ["id", "scope_cabin"])

    for column in (
        sa.Column("fault_type", sa.Text),
        sa.Column("cabin", sa.Text),
        sa.Column("ticket_ref", sa.Text),
        sa.Column("ticket_status", sa.Text),
        sa.Column("ticket_version", sa.Integer),
        sa.Column("same_report_id", sa.BigInteger),
    ):
        op.add_column("tasks", column)
    op.execute("UPDATE tasks SET fault_type = 'other' WHERE kind = 'fault'")
    op.drop_constraint("ck_tasks_state", "tasks", type_="check")
    op.create_check_constraint("ck_tasks_state", "tasks", f"state IN {TASK_STATES}")
    op.create_check_constraint(
        "ck_tasks_fault_type",
        "tasks",
        f"(kind = 'fault') = (fault_type IS NOT NULL) AND (fault_type IS NULL"
        f" OR fault_type IN {FAULT_TYPES})",
    )
    op.create_check_constraint(
        "ck_tasks_ticket",
        "tasks",
        "(ticket_ref IS NULL AND ticket_status IS NULL AND ticket_version IS NULL)"
        " OR (ticket_ref IS NOT NULL AND ticket_version IS NOT NULL AND cabin IS NOT NULL"
        f" AND kind = 'fault' AND ticket_status IN {TICKET_STATES})",
    )
    op.create_check_constraint(
        "ck_tasks_ticketed", "tasks", "state <> 'ticketed' OR ticket_ref IS NOT NULL"
    )
    op.create_check_constraint(
        "ck_tasks_same_report",
        "tasks",
        "state NOT IN ('awaiting_same', 'linking') OR same_report_id IS NOT NULL",
    )
    op.create_foreign_key(
        "fk_tasks_case_cabin", "tasks", "cases", ["case_id", "cabin"], ["id", "scope_cabin"]
    )

    op.create_table(
        "reports",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("cabin", sa.Text, nullable=False),
        sa.Column("fault_type", sa.Text, nullable=False),
        sa.Column("case_id", sa.BigInteger, nullable=False),
        sa.Column("step_id", sa.Text, nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column(
            "checked_against",
            postgresql.ARRAY(sa.BigInteger),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("case_id", "step_id", name="uq_reports_case_step"),
        sa.ForeignKeyConstraint(
            ["case_id", "step_id"],
            ["tasks.case_id", "tasks.step_id"],
            name="fk_reports_task",
        ),
        sa.CheckConstraint(f"fault_type IN {FAULT_TYPES}", name="ck_reports_fault_type"),
    )
    op.create_index("ix_reports_cabin", "reports", ["cabin", "id"])
    op.create_foreign_key("fk_tasks_same_report", "tasks", "reports", ["same_report_id"], ["id"])

    op.create_table(
        "validation_records",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("case_id", sa.BigInteger, nullable=False),
        sa.Column("step_id", sa.Text, nullable=False),
        sa.Column("outcome", sa.Text, nullable=False),
        sa.Column("args", postgresql.JSONB, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["case_id", "step_id"],
            ["tasks.case_id", "tasks.step_id"],
            name="fk_validation_records_task",
        ),
        sa.CheckConstraint("outcome IN ('pass', 'block')", name="ck_validation_records_outcome"),
    )
    op.create_index("ix_validation_records_step", "validation_records", ["case_id", "step_id"])


def downgrade() -> None:
    op.drop_table("validation_records")
    op.drop_constraint("fk_tasks_same_report", "tasks", type_="foreignkey")
    op.drop_table("reports")
    op.drop_constraint("fk_tasks_case_cabin", "tasks", type_="foreignkey")
    for name in (
        "ck_tasks_same_report",
        "ck_tasks_ticketed",
        "ck_tasks_ticket",
        "ck_tasks_fault_type",
        "ck_tasks_state",
    ):
        op.drop_constraint(name, "tasks", type_="check")
    op.create_check_constraint(
        "ck_tasks_state", "tasks", "state IN ('queued', 'awaiting_scope', 'held', 'done')"
    )
    for column in (
        "same_report_id",
        "ticket_version",
        "ticket_status",
        "ticket_ref",
        "cabin",
        "fault_type",
    ):
        op.drop_column("tasks", column)
    op.drop_constraint("uq_cases_id_scope_cabin", "cases", type_="unique")
    _state_reason(OLD_HELD_REASONS)


def _state_reason(held: str) -> None:
    op.drop_constraint("ck_cases_state_reason", "cases", type_="check")
    op.create_check_constraint(
        "ck_cases_state_reason",
        "cases",
        "(state = 'open' AND state_reason IS NULL)"
        f" OR (state = 'held' AND state_reason IN {held})"
        " OR (state = 'parked' AND state_reason IN ('spam', 'verification'))",
    )

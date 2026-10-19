"""booking requests: party, date and time on table tasks

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TASK_STATES = (
    "('queued', 'awaiting_scope', 'held', 'done', 'awaiting_split', 'split_confirmed',"
    " 'awaiting_same', 'drafting', 'linking', 'ticketed', 'booking_requested')"
)
OLD_TASK_STATES = (
    "('queued', 'awaiting_scope', 'held', 'done', 'awaiting_split', 'split_confirmed',"
    " 'awaiting_same', 'drafting', 'linking', 'ticketed')"
)
HELD_REASONS = (
    "('emergency', 'money', 'llm_failed', 'clarify_limit', 'fault_review', 'ticketing_down',"
    " 'booking_review')"
)
OLD_HELD_REASONS = (
    "('emergency', 'money', 'llm_failed', 'clarify_limit', 'fault_review', 'ticketing_down')"
)


def upgrade() -> None:
    _state_reason(HELD_REASONS)
    _task_states(TASK_STATES)
    for column in (
        sa.Column("booking_party", sa.Integer),
        sa.Column("booking_date", sa.Date),
        sa.Column("booking_time", sa.Time),
    ):
        op.add_column("tasks", column)
    # The cabin column carries the booking into the I5 composite key, as it does a ticket.
    op.create_check_constraint(
        "ck_tasks_booking",
        "tasks",
        "(booking_party IS NULL AND booking_date IS NULL AND booking_time IS NULL)"
        " OR (kind = 'table' AND cabin IS NOT NULL AND booking_party > 0"
        " AND booking_date IS NOT NULL AND booking_time IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_tasks_booking_requested",
        "tasks",
        "state <> 'booking_requested' OR booking_party IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_tasks_booking_requested", "tasks", type_="check")
    op.drop_constraint("ck_tasks_booking", "tasks", type_="check")
    for column in ("booking_time", "booking_date", "booking_party"):
        op.drop_column("tasks", column)
    _task_states(OLD_TASK_STATES)
    _state_reason(OLD_HELD_REASONS)


def _task_states(states: str) -> None:
    op.drop_constraint("ck_tasks_state", "tasks", type_="check")
    op.create_check_constraint("ck_tasks_state", "tasks", f"state IN {states}")


def _state_reason(held: str) -> None:
    op.drop_constraint("ck_cases_state_reason", "cases", type_="check")
    op.create_check_constraint(
        "ck_cases_state_reason",
        "cases",
        "(state = 'open' AND state_reason IS NULL)"
        f" OR (state = 'held' AND state_reason IN {held})"
        " OR (state = 'parked' AND state_reason IN ('spam', 'verification'))",
    )

"""case close and reopen, booking confirm and decline

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TASK_STATES = (
    "('queued', 'awaiting_scope', 'held', 'done', 'awaiting_split', 'split_confirmed',"
    " 'awaiting_same', 'drafting', 'linking', 'ticketed', 'booking_requested',"
    " 'booking_confirmed', 'booking_declined')"
)
OLD_TASK_STATES = (
    "('queued', 'awaiting_scope', 'held', 'done', 'awaiting_split', 'split_confirmed',"
    " 'awaiting_same', 'drafting', 'linking', 'ticketed', 'booking_requested')"
)
HELD_REASONS = (
    "('emergency', 'money', 'llm_failed', 'clarify_limit', 'fault_review', 'ticketing_down',"
    " 'booking_review')"
)


def upgrade() -> None:
    op.add_column("cases", sa.Column("closed_at", sa.DateTime(timezone=True)))
    op.drop_constraint("ck_cases_state", "cases", type_="check")
    op.create_check_constraint(
        "ck_cases_state", "cases", "state IN ('open', 'held', 'parked', 'closed')"
    )
    _state_reason("OR (state = 'closed' AND state_reason IS NULL)")
    op.create_check_constraint(
        "ck_cases_closed_at", "cases", "(state = 'closed') = (closed_at IS NOT NULL)"
    )
    _task_states(TASK_STATES)
    op.drop_constraint("ck_tasks_booking_requested", "tasks", type_="check")
    op.create_check_constraint(
        "ck_tasks_booking_requested",
        "tasks",
        "state NOT IN ('booking_requested', 'booking_confirmed', 'booking_declined')"
        " OR booking_party IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_tasks_booking_requested", "tasks", type_="check")
    op.create_check_constraint(
        "ck_tasks_booking_requested",
        "tasks",
        "state <> 'booking_requested' OR booking_party IS NOT NULL",
    )
    _task_states(OLD_TASK_STATES)
    op.drop_constraint("ck_cases_closed_at", "cases", type_="check")
    _state_reason("")
    op.drop_constraint("ck_cases_state", "cases", type_="check")
    op.create_check_constraint("ck_cases_state", "cases", "state IN ('open', 'held', 'parked')")
    op.drop_column("cases", "closed_at")


def _task_states(states: str) -> None:
    op.drop_constraint("ck_tasks_state", "tasks", type_="check")
    op.create_check_constraint("ck_tasks_state", "tasks", f"state IN {states}")


def _state_reason(closed: str) -> None:
    op.drop_constraint("ck_cases_state_reason", "cases", type_="check")
    op.create_check_constraint(
        "ck_cases_state_reason",
        "cases",
        "(state = 'open' AND state_reason IS NULL)"
        f" OR (state = 'held' AND state_reason IN {HELD_REASONS})"
        " OR (state = 'parked' AND state_reason IN ('spam', 'verification'))"
        f" {closed}",
    )

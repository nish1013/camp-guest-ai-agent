"""staff resolve: rejected tasks

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-19

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TASK_STATES = (
    "('queued', 'awaiting_scope', 'held', 'done', 'awaiting_split', 'split_confirmed',"
    " 'awaiting_same', 'drafting', 'linking', 'ticketed', 'booking_requested',"
    " 'booking_confirmed', 'booking_declined', 'rejected')"
)
OLD_TASK_STATES = (
    "('queued', 'awaiting_scope', 'held', 'done', 'awaiting_split', 'split_confirmed',"
    " 'awaiting_same', 'drafting', 'linking', 'ticketed', 'booking_requested',"
    " 'booking_confirmed', 'booking_declined')"
)


def upgrade() -> None:
    _task_states(TASK_STATES)


def downgrade() -> None:
    _task_states(OLD_TASK_STATES)


def _task_states(states: str) -> None:
    op.drop_constraint("ck_tasks_state", "tasks", type_="check")
    op.create_check_constraint("ck_tasks_state", "tasks", f"state IN {states}")

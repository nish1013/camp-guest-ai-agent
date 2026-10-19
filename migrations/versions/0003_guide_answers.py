"""guide answers on question tasks

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("answer", sa.Text))
    op.add_column("tasks", sa.Column("answer_section", sa.Text))
    op.drop_constraint("ck_tasks_state", "tasks", type_="check")
    op.create_check_constraint(
        "ck_tasks_state", "tasks", "state IN ('queued', 'awaiting_scope', 'held', 'done')"
    )
    op.create_check_constraint(
        "ck_tasks_answer",
        "tasks",
        "(answer IS NULL AND answer_section IS NULL)"
        " OR (kind = 'question' AND state = 'done' AND answer IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_tasks_answer", "tasks", type_="check")
    op.drop_constraint("ck_tasks_state", "tasks", type_="check")
    op.create_check_constraint(
        "ck_tasks_state", "tasks", "state IN ('queued', 'awaiting_scope', 'held')"
    )
    op.drop_column("tasks", "answer_section")
    op.drop_column("tasks", "answer")

"""quick picks: the topic a guest tapped with a new request

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PICKS = "('maintenance', 'cleaning', 'restaurant', 'question', 'reception')"


def upgrade() -> None:
    op.add_column("messages", sa.Column("pick", sa.Text))
    op.create_check_constraint("ck_messages_pick", "messages", f"pick IN {PICKS}")


def downgrade() -> None:
    op.drop_constraint("ck_messages_pick", "messages", type_="check")
    op.drop_column("messages", "pick")

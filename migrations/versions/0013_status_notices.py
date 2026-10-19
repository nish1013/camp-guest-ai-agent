"""status notices: the last guest status sent to the notification port, per case

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "status_notices",
        sa.Column("case_id", sa.BigInteger, sa.ForeignKey("cases.id"), primary_key=True),
        sa.Column("digest", sa.Text, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("status_notices")

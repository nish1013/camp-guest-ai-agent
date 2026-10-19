"""cases and messages

Revision ID: 0001
Revises:
Create Date: 2026-10-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cases",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("case_token", sa.Text, nullable=False),
        sa.Column("scope_cabin", sa.Text),
        sa.Column("scope_stay_from", sa.Date),
        sa.Column("scope_stay_to", sa.Date),
        sa.Column("scope_source", sa.Text),
        sa.Column("state", sa.Text, nullable=False, server_default="open"),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("run_lease_owner", sa.Uuid),
        sa.Column("run_lease_until", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("case_token", name="uq_cases_case_token"),
        sa.CheckConstraint(
            "(scope_cabin IS NULL AND scope_stay_from IS NULL AND scope_stay_to IS NULL"
            " AND scope_source IS NULL)"
            " OR (scope_cabin IS NOT NULL AND scope_stay_from IS NOT NULL"
            " AND scope_stay_to IS NOT NULL AND scope_source IS NOT NULL"
            " AND scope_source IN ('qr', 'step_up', 'staff'))",
            name="ck_cases_scope_source",
        ),
        sa.CheckConstraint("scope_stay_from <= scope_stay_to", name="ck_cases_stay_order"),
        sa.CheckConstraint("state IN ('open')", name="ck_cases_state"),
        sa.CheckConstraint(
            "(run_lease_owner IS NULL) = (run_lease_until IS NULL)", name="ck_cases_run_lease"
        ),
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("idempotency_key", sa.Uuid, nullable=False),
        sa.Column("case_id", sa.BigInteger, sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("handled_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("idempotency_key", name="uq_messages_idempotency_key"),
    )
    op.create_index(
        "ix_messages_pending",
        "messages",
        ["case_id", "id"],
        postgresql_where=sa.text("handled_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("messages")
    op.drop_table("cases")

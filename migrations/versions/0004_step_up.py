"""step-up: verification attempts, failures per IP, parked after verification

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECKS = "('matched', 'no_booking', 'wrong_surname', 'cabin_differs', 'stay_inactive')"


def upgrade() -> None:
    _state_reason("('spam', 'verification')")
    op.create_table(
        "verification_attempts",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("case_id", sa.BigInteger, sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("outcome", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"outcome IN {CHECKS}", name="ck_verification_attempts_outcome"),
    )
    op.create_index("ix_verification_attempts_case", "verification_attempts", ["case_id"])
    op.create_table(
        "ip_verification_failures",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("ip", sa.Text, nullable=False),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_ip_verification_failures_ip", "ip_verification_failures", ["ip", "failed_at"]
    )


def downgrade() -> None:
    op.drop_table("ip_verification_failures")
    op.drop_table("verification_attempts")
    _state_reason("('spam')")


def _state_reason(parked: str) -> None:
    op.drop_constraint("ck_cases_state_reason", "cases", type_="check")
    op.create_check_constraint(
        "ck_cases_state_reason",
        "cases",
        "(state = 'open' AND state_reason IS NULL)"
        " OR (state = 'held'"
        " AND state_reason IN ('emergency', 'money', 'llm_failed', 'clarify_limit'))"
        f" OR (state = 'parked' AND state_reason IN {parked})",
    )

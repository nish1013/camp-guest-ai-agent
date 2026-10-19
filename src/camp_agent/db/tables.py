from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    Table,
    Text,
    Time,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()

cases = Table(
    "cases",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("case_token", Text, nullable=False, unique=True),
    Column("scope_cabin", Text),
    Column("scope_stay_from", Date),
    Column("scope_stay_to", Date),
    Column("scope_source", Text),
    Column("state", Text, nullable=False),
    Column("state_reason", Text),
    Column("safety", Boolean, nullable=False),
    Column("urgency", Text, nullable=False),
    Column("clarify_rounds", Integer, nullable=False),
    Column("held_at", DateTime(timezone=True)),
    Column("closed_at", DateTime(timezone=True)),
    Column("version", Integer, nullable=False),
    Column("run_lease_owner", Uuid),
    Column("run_lease_until", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

messages = Table(
    "messages",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("idempotency_key", Uuid, nullable=False, unique=True),
    Column("case_id", BigInteger, ForeignKey("cases.id"), nullable=False),
    Column("text", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("handled_at", DateTime(timezone=True)),
    Column("parked", Boolean, nullable=False),
    Column("restored", Boolean, nullable=False),
    Column("pick", Text),
)

tasks = Table(
    "tasks",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("case_id", BigInteger, ForeignKey("cases.id"), nullable=False),
    Column("step_id", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("category", Text),
    Column("urgency", Text, nullable=False),
    Column("state", Text, nullable=False),
    Column("summary", Text, nullable=False),
    Column("answer", Text),
    Column("answer_section", Text),
    Column("fault_type", Text),
    Column("cabin", Text),
    Column("ticket_ref", Text),
    Column("ticket_status", Text),
    Column("ticket_version", Integer),
    Column("same_report_id", BigInteger),
    Column("booking_party", Integer),
    Column("booking_date", Date),
    Column("booking_time", Time),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

reports = Table(
    "reports",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("cabin", Text, nullable=False),
    Column("fault_type", Text, nullable=False),
    Column("case_id", BigInteger, nullable=False),
    Column("step_id", Text, nullable=False),
    Column("summary", Text, nullable=False),
    Column("checked_against", ARRAY(BigInteger), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

validation_records = Table(
    "validation_records",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("case_id", BigInteger, nullable=False),
    Column("step_id", Text, nullable=False),
    Column("outcome", Text, nullable=False),
    Column("args", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

demo_tickets = Table(
    "demo_tickets",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("case_id", BigInteger, nullable=False),
    Column("step_id", Text, nullable=False),
    Column("cabin", Text, nullable=False),
    Column("team", Text, nullable=False),
    Column("fault_type", Text, nullable=False),
    Column("urgency", Text, nullable=False),
    Column("summary", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("version", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

audit_entries = Table(
    "audit_entries",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("case_id", BigInteger, ForeignKey("cases.id"), nullable=False),
    Column("step", Text, nullable=False),
    Column("decision", Text, nullable=False),
    Column("detail", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

verification_attempts = Table(
    "verification_attempts",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("case_id", BigInteger, ForeignKey("cases.id"), nullable=False),
    Column("outcome", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

ip_verification_failures = Table(
    "ip_verification_failures",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("ip", Text, nullable=False),
    Column("failed_at", DateTime(timezone=True), nullable=False),
)

ticket_events = Table(
    "ticket_events",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("ticket_ref", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("version", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

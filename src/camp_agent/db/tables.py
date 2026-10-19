from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    Table,
    Text,
    Uuid,
)

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
)

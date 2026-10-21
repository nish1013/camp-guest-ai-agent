from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from camp_agent.db.tables import audit_entries, validation_records
from camp_agent.domain.cases import AuditEntry
from camp_agent.graph.triage import ValidationRecord


@dataclass(frozen=True)
class StaffAuditLine:
    step: str
    decision: str
    detail: Mapping[str, object]
    created_at: datetime


class AuditRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def insert(self, case_id: int, entry: AuditEntry) -> None:
        await self._conn.execute(
            insert(audit_entries).values(
                case_id=case_id,
                step=entry.step,
                decision=entry.decision,
                detail=dict(entry.detail),
            )
        )

    async def for_case(self, case_id: int) -> list[StaffAuditLine]:
        query = (
            select(audit_entries)
            .where(audit_entries.c.case_id == case_id)
            .order_by(audit_entries.c.id)
        )
        rows = (await self._conn.execute(query)).all()
        return [StaffAuditLine(row.step, row.decision, row.detail, row.created_at) for row in rows]


class ValidationRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def insert(self, case_id: int, record: ValidationRecord) -> None:
        await self._conn.execute(
            insert(validation_records).values(
                case_id=case_id,
                step_id=record.step_id,
                outcome=record.outcome,
                args=dict(record.args),
            )
        )

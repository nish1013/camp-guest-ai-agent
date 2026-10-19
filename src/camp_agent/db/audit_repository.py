from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from camp_agent.db.tables import audit_entries
from camp_agent.domain.audit_entry import AuditEntry


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

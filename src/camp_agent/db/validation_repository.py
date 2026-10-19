from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from camp_agent.db.tables import validation_records
from camp_agent.graph.triage_types import ValidationRecord


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

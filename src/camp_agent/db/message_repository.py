from datetime import datetime
from uuid import UUID

from sqlalchemy import exists, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from camp_agent.db.staff_rows import StaffMessage
from camp_agent.db.tables import messages
from camp_agent.domain.quick_pick import QuickPick
from camp_agent.graph.triage_graph import PendingMessage


class MessageRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def find_case_id(self, idempotency_key: UUID) -> int | None:
        query = select(messages.c.case_id).where(messages.c.idempotency_key == idempotency_key)
        case_id: int | None = (await self._conn.execute(query)).scalar_one_or_none()
        return case_id

    async def insert(
        self, idempotency_key: UUID, case_id: int, text: str, pick: QuickPick | None = None
    ) -> bool:
        inserted = await self._conn.execute(
            insert(messages)
            .values(idempotency_key=idempotency_key, case_id=case_id, text=text, pick=pick)
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
            .returning(messages.c.id)
        )
        return inserted.one_or_none() is not None

    async def pending(self, case_id: int) -> list[PendingMessage]:
        query = (
            select(messages.c.id, messages.c.text, messages.c.restored, messages.c.pick)
            .where(messages.c.case_id == case_id, messages.c.handled_at.is_(None))
            .order_by(messages.c.id)
        )
        rows = (await self._conn.execute(query)).all()
        return [
            PendingMessage(
                row.id, row.text, row.restored, None if row.pick is None else QuickPick(row.pick)
            )
            for row in rows
        ]

    async def for_staff(self, case_id: int) -> list[StaffMessage]:
        query = (
            select(messages.c.id, messages.c.text, messages.c.created_at)
            .where(messages.c.case_id == case_id)
            .order_by(messages.c.id)
        )
        rows = (await self._conn.execute(query)).all()
        return [StaffMessage(row.id, row.text, row.created_at) for row in rows]

    async def has_pending(self, case_id: int) -> bool:
        query = select(
            exists().where(messages.c.case_id == case_id, messages.c.handled_at.is_(None))
        )
        found: bool = (await self._conn.execute(query)).scalar_one()
        return found

    async def mark_handled(self, message_ids: list[int], now: datetime, parked: bool) -> None:
        await self._conn.execute(
            update(messages)
            .where(messages.c.id.in_(message_ids), messages.c.handled_at.is_(None))
            .values(handled_at=now, parked=parked, restored=False)
        )

    async def requeue_parked(self, case_id: int, restored: bool) -> int:
        queued = await self._conn.execute(
            update(messages)
            .where(messages.c.case_id == case_id, messages.c.parked)
            .values(handled_at=None, parked=False, restored=restored)
            .returning(messages.c.id)
        )
        return len(queued.all())

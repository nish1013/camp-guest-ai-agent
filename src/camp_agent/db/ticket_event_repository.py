from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from camp_agent.db.outbox_row import OutboxRow
from camp_agent.db.tables import ticket_events
from camp_agent.domain.ticket_status import TicketStatus
from camp_agent.ticket.ticket_types import TicketStatusChanged


class TicketEventRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def insert(self, event: TicketStatusChanged) -> None:
        await self._conn.execute(
            insert(ticket_events).values(
                ticket_ref=event.ticket_ref, status=event.status, version=event.version
            )
        )

    async def oldest(self, limit: int) -> list[OutboxRow]:
        query = select(ticket_events).order_by(ticket_events.c.id).limit(limit)
        rows = (await self._conn.execute(query)).all()
        return [
            OutboxRow(
                row.id, TicketStatusChanged(row.ticket_ref, TicketStatus(row.status), row.version)
            )
            for row in rows
        ]

    async def delete(self, row_id: int) -> None:
        await self._conn.execute(delete(ticket_events).where(ticket_events.c.id == row_id))

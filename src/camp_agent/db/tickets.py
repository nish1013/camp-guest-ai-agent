from dataclasses import dataclass

from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from camp_agent.db.tables import ticket_events
from camp_agent.domain.faults import TicketStatus
from camp_agent.ticket.port import TicketStatusChanged


@dataclass(frozen=True)
class OutboxRow:
    id: int
    event: TicketStatusChanged


# First key of the two-key advisory lock: keeps ticket locks apart from cabin locks.
_TICKET_LOCK = 5


async def lock_ticket_xact(conn: AsyncConnection, ticket_ref: str) -> None:
    await conn.execute(select(func.pg_advisory_xact_lock(_TICKET_LOCK, func.hashtext(ticket_ref))))


async def lock_ticket(conn: AsyncConnection, ticket_ref: str) -> None:
    await conn.execute(select(func.pg_advisory_lock(_TICKET_LOCK, func.hashtext(ticket_ref))))


async def unlock_ticket(conn: AsyncConnection, ticket_ref: str) -> None:
    await conn.execute(select(func.pg_advisory_unlock(_TICKET_LOCK, func.hashtext(ticket_ref))))


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

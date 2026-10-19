import re

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine

from camp_agent.db.tables import demo_tickets
from camp_agent.db.ticket_event_repository import TicketEventRepository
from camp_agent.domain.ticket_status import TicketStatus
from camp_agent.ticket.ticket_types import TicketStatusChanged

_REF = re.compile(r"^T(\d+)$")


class DemoTicketStatus:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    # The demo ticket system writes its outbox row in the status change's transaction (D10, I12).
    async def set(self, ticket_ref: str, status: TicketStatus) -> TicketStatusChanged | None:
        match = _REF.match(ticket_ref)
        if match is None:
            return None
        async with self._engine.begin() as conn:
            changed = await conn.execute(
                update(demo_tickets)
                .where(demo_tickets.c.id == int(match.group(1)))
                .values(status=status, version=demo_tickets.c.version + 1)
                .returning(demo_tickets.c.version)
            )
            version = changed.scalar_one_or_none()
            if version is None:
                return None
            event = TicketStatusChanged(ticket_ref, status, version)
            await TicketEventRepository(conn).insert(event)
        return event

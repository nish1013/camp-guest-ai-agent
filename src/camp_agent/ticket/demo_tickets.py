import re

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from camp_agent.db.tables import demo_tickets
from camp_agent.db.tickets import TicketEventRepository
from camp_agent.domain.faults import TicketStatus
from camp_agent.ticket.port import TicketError, TicketReceipt, TicketRequest, TicketStatusChanged

_RECEIPT = (demo_tickets.c.id, demo_tickets.c.status, demo_tickets.c.version)


class DemoTickets:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def create(self, request: TicketRequest) -> TicketReceipt:
        key = request.key
        try:
            async with self._engine.begin() as conn:
                created = await conn.execute(
                    insert(demo_tickets)
                    .values(
                        case_id=key.case_id,
                        step_id=key.step_id,
                        cabin=request.cabin,
                        team=request.team,
                        fault_type=request.fault_type,
                        urgency=request.urgency,
                        summary=request.summary,
                        status=TicketStatus.OPEN,
                        version=1,
                    )
                    .on_conflict_do_nothing(index_elements=["case_id", "step_id"])
                    .returning(*_RECEIPT)
                )
                row = created.one_or_none()
                if row is None:
                    existing = select(*_RECEIPT).where(
                        demo_tickets.c.case_id == key.case_id,
                        demo_tickets.c.step_id == key.step_id,
                    )
                    row = (await conn.execute(existing)).one()
        except (SQLAlchemyError, OSError) as error:
            raise TicketError(type(error).__name__) from error
        return TicketReceipt(f"T{row.id}", TicketStatus(row.status), row.version)


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

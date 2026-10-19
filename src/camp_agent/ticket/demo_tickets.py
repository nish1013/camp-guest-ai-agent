from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from camp_agent.db.tables import demo_tickets
from camp_agent.domain.ticket_status import TicketStatus
from camp_agent.ticket.ticket_error import TicketError
from camp_agent.ticket.ticket_types import TicketReceipt, TicketRequest

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

import pytest
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncEngine

from camp_agent.domain.fault_type import FaultType
from camp_agent.domain.specialist import Team
from camp_agent.domain.ticket_status import TicketStatus
from camp_agent.domain.urgency import Urgency
from camp_agent.ticket.demo_tickets import DemoTickets
from camp_agent.ticket.ticket_types import TicketKey, TicketReceipt, TicketRequest
from tests.integration.intake_support import count

pytestmark = pytest.mark.anyio


def request(step_id: str) -> TicketRequest:
    return TicketRequest(
        TicketKey(1, step_id), "C12", Team.MAINTENANCE, FaultType.LEAK, Urgency.URGENT, "Tap leaks"
    )


async def test_d5_repeat_key_same_ticket(db: Engine, async_db: AsyncEngine) -> None:
    tickets = DemoTickets(async_db)

    first = await tickets.create(request("m1/t0"))
    again = await tickets.create(request("m1/t0"))
    other = await tickets.create(request("m1/t1"))

    assert first == again == TicketReceipt("T1", TicketStatus.OPEN, 1)
    assert other.ref != first.ref
    assert count(db, "demo_tickets") == 2

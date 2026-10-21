import pytest

from camp_agent.domain.faults import FaultType, TicketStatus
from camp_agent.domain.routing import Team, Urgency
from camp_agent.ticket.port import TicketError, TicketKey, TicketReceipt, TicketRequest
from camp_agent.ticket.retrying_tickets import RetryingTickets

pytestmark = pytest.mark.anyio

REQUEST = TicketRequest(
    TicketKey(1, "m1/t0"), "C12", Team.MAINTENANCE, FaultType.LEAK, Urgency.URGENT, "Tap leaks"
)


class FlakyTickets:
    def __init__(self, failures: int) -> None:
        self._failures = failures
        self.calls = 0

    async def create(self, request: TicketRequest) -> TicketReceipt:
        self.calls += 1
        if self.calls <= self._failures:
            raise TicketError("timeout")
        return TicketReceipt("T1", TicketStatus.OPEN, 1)


async def test_d43_retry_then_created() -> None:
    inner = FlakyTickets(failures=2)

    receipt = await RetryingTickets(inner, attempts=3, delay_s=0).create(REQUEST)

    assert (receipt.ref, inner.calls) == ("T1", 3)


async def test_d43_retries_are_bounded() -> None:
    inner = FlakyTickets(failures=3)

    with pytest.raises(TicketError):
        await RetryingTickets(inner, attempts=3, delay_s=0).create(REQUEST)
    assert inner.calls == 3

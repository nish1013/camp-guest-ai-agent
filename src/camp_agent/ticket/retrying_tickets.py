import anyio

from camp_agent.ticket.ticket_error import TicketError
from camp_agent.ticket.ticket_port import TicketPort
from camp_agent.ticket.ticket_types import TicketReceipt, TicketRequest


class RetryingTickets:
    def __init__(self, inner: TicketPort, attempts: int, delay_s: float) -> None:
        if attempts < 1:
            raise ValueError("attempts must be at least 1")
        self._inner = inner
        self._attempts = attempts
        self._delay_s = delay_s

    # A retry is safe: create is idempotent on the request key (I3).
    async def create(self, request: TicketRequest) -> TicketReceipt:
        for attempt in range(1, self._attempts + 1):
            try:
                return await self._inner.create(request)
            except TicketError:
                if attempt == self._attempts:
                    raise
                await anyio.sleep(self._delay_s)
        raise AssertionError("unreachable")

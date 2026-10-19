from typing import Protocol

from camp_agent.ticket.ticket_types import TicketReceipt, TicketRequest


class TicketPort(Protocol):
    # A repeat key returns the ticket already created for it, never a second one (D5, I3).
    # Adapters raise TicketError when the ticket system cannot be reached.
    async def create(self, request: TicketRequest) -> TicketReceipt: ...

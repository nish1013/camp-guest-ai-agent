from dataclasses import dataclass

from camp_agent.ticket.ticket_types import TicketStatusChanged


@dataclass(frozen=True)
class OutboxRow:
    id: int
    event: TicketStatusChanged

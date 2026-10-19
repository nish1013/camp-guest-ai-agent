from enum import StrEnum


class TicketStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"


CLOSED_TICKET_STATES = frozenset({TicketStatus.DONE, TicketStatus.CANCELLED})

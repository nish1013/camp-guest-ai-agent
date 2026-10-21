from dataclasses import dataclass
from typing import Protocol

from camp_agent.domain.faults import FaultType, TicketStatus
from camp_agent.domain.routing import Team, Urgency


class TicketError(Exception):
    pass


@dataclass(frozen=True)
class TicketKey:
    case_id: int
    step_id: str


@dataclass(frozen=True)
class TicketRequest:
    key: TicketKey
    cabin: str
    team: Team
    fault_type: FaultType
    urgency: Urgency
    summary: str


@dataclass(frozen=True)
class TicketReceipt:
    ref: str
    status: TicketStatus
    version: int


@dataclass(frozen=True)
class TicketStatusChanged:
    ticket_ref: str
    status: TicketStatus
    version: int


class TicketPort(Protocol):
    # A repeat key returns the ticket already created for it, never a second one (D5, I3).
    # Adapters raise TicketError when the ticket system cannot be reached.
    async def create(self, request: TicketRequest) -> TicketReceipt: ...

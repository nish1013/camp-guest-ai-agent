from dataclasses import dataclass

from camp_agent.domain.fault_type import FaultType
from camp_agent.domain.specialist import Team
from camp_agent.domain.ticket_status import TicketStatus
from camp_agent.domain.urgency import Urgency


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

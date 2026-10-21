from dataclasses import dataclass

from camp_agent.domain.faults import OpenReport
from camp_agent.domain.guest_status import QuickPick
from camp_agent.domain.routing import Team


@dataclass(frozen=True)
class ClassifyInput:
    intent: str
    pick: QuickPick | None = None


@dataclass(frozen=True)
class SameProblemInput:
    fault: str
    earlier: tuple[OpenReport, ...]


@dataclass(frozen=True)
class TicketInput:
    team: Team
    fault: str


@dataclass(frozen=True)
class GraphOutcome:
    emergency: bool
    parked: bool

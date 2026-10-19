from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time

from camp_agent.domain.route_guard import Category, TaskKind, TaskState
from camp_agent.domain.ticket_status import TicketStatus
from camp_agent.domain.urgency import Urgency


@dataclass(frozen=True)
class TaskRef:
    case_id: int
    step_id: str


@dataclass(frozen=True)
class StaffTask:
    id: int
    step_id: str
    kind: TaskKind
    category: Category | None
    urgency: Urgency
    state: TaskState
    summary: str
    ticket_ref: str | None
    ticket_status: TicketStatus | None
    booking_party: int | None
    booking_date: date | None
    booking_time: time | None


@dataclass(frozen=True)
class StaffMessage:
    id: int
    text: str
    created_at: datetime


@dataclass(frozen=True)
class StaffAuditLine:
    step: str
    decision: str
    detail: Mapping[str, object]
    created_at: datetime

from dataclasses import dataclass

from camp_agent.db.case_record import CaseRecord
from camp_agent.db.staff_rows import StaffAuditLine, StaffMessage, StaffTask
from camp_agent.domain.route_guard import Category
from camp_agent.domain.urgency import Urgency


@dataclass(frozen=True)
class QueueItem:
    case: CaseRecord
    overdue: bool


@dataclass(frozen=True)
class CaseDetail:
    case: CaseRecord
    overdue: bool
    tasks: list[StaffTask]
    messages: list[StaffMessage]
    audit: list[StaffAuditLine]


@dataclass(frozen=True)
class BookingDecision:
    task_id: int
    version: int
    confirm: bool


@dataclass(frozen=True)
class ResolveCommand:
    case_id: int
    version: int
    approve: bool
    step_id: str | None = None
    category: Category | None = None
    urgency: Urgency | None = None

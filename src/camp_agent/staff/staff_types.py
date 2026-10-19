from dataclasses import dataclass

from camp_agent.db.case_record import CaseRecord
from camp_agent.db.staff_rows import StaffAuditLine, StaffMessage, StaffTask


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

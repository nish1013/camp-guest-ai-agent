from dataclasses import dataclass

from camp_agent.db.case_record import CaseRecord


@dataclass(frozen=True)
class QueueItem:
    case: CaseRecord
    overdue: bool

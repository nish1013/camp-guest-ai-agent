from dataclasses import dataclass
from datetime import datetime

from camp_agent.domain.case_status import CaseStatus
from camp_agent.domain.scope import Scope


@dataclass(frozen=True)
class CaseRecord:
    id: int
    case_token: str
    status: CaseStatus
    scope: Scope | None
    version: int
    created_at: datetime

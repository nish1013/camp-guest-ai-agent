from dataclasses import dataclass

from camp_agent.domain.case_state import CaseState
from camp_agent.domain.scope import Scope


@dataclass(frozen=True)
class CaseRecord:
    id: int
    case_token: str
    state: CaseState
    scope: Scope | None

from dataclasses import dataclass
from datetime import datetime

from camp_agent.domain.fault_type import FaultType


@dataclass(frozen=True)
class ReportDraft:
    cabin: str
    fault_type: FaultType
    step_id: str
    summary: str
    at: datetime


@dataclass(frozen=True)
class OpenReport:
    id: int
    fault_type: FaultType
    summary: str
    at: datetime


@dataclass(frozen=True)
class SavedReport:
    id: int
    checked_against: tuple[OpenReport, ...]

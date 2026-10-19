from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum

from camp_agent.db.case_record import CaseRecord


class StepUpResult(StrEnum):
    MATCHED = "matched"
    NO_MATCH = "no_match"
    LOCKED = "locked"
    BOOKINGS_DOWN = "bookings_down"
    ALREADY_SCOPED = "already_scoped"


@dataclass(frozen=True)
class StepUpCommand:
    case_token: str
    surname: str
    booking_ref: str
    cabin_hint: str | None
    client_ip: str


@dataclass(frozen=True)
class StepUpReply:
    result: StepUpResult
    case: CaseRecord


@dataclass(frozen=True)
class StepUpLimits:
    case_failures: int
    ip_failures: int
    ip_window: timedelta

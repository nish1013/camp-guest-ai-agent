from dataclasses import dataclass

from camp_agent.db.case_record import CaseRecord
from camp_agent.domain.fault_flow import Confirmation


@dataclass(frozen=True)
class AnswerCommand:
    case_token: str
    confirmation: Confirmation
    subject: str
    yes: bool


@dataclass(frozen=True)
class AnswerReply:
    case: CaseRecord
    # The answer moved a waiting task, so a run must pick it up.
    moved: bool


@dataclass(frozen=True)
class TicketLine:
    fault: str
    status: str


@dataclass(frozen=True)
class BookingLine:
    request: str
    status: str


@dataclass(frozen=True)
class QuestionView:
    confirmation: Confirmation
    subject: str
    text: str


@dataclass(frozen=True)
class CaseFaults:
    tickets: list[TicketLine]
    questions: list[QuestionView]

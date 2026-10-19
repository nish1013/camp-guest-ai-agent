import datetime as dt
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel

from camp_agent.domain.fault_type import FaultType
from camp_agent.domain.route_guard import Category, Route
from camp_agent.domain.urgency import Urgency


class Verdict(StrEnum):
    GENUINE = "genuine"
    SPAM = "spam"
    UNCLEAR = "unclear"


class VerifyOutput(BaseModel):
    verdict: Verdict


class SplitOutput(BaseModel):
    intents: list[str]


class GuideAnswer(BaseModel):
    text: str
    section_id: str | None


class Classification(BaseModel):
    category: Category
    route: Route
    urgency: Urgency
    fault_type: FaultType | None = None


class SameProblem(BaseModel):
    report_id: int | None


class TicketArgs(BaseModel):
    tool: str
    cabin: str
    summary: str


@dataclass(frozen=True)
class TicketBrief:
    fault: str
    cabin: str
    rejected_for: tuple[str, ...] = ()


class TableArgs(BaseModel):
    tool: str
    cabin: str
    party: int | None
    date: dt.date | None
    time: dt.time | None


@dataclass(frozen=True)
class TableBrief:
    request: str
    cabin: str
    today: dt.date
    stay_from: dt.date
    stay_to: dt.date
    rejected_for: tuple[str, ...] = ()

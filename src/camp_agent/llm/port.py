import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Protocol

from pydantic import AfterValidator, BaseModel, WithJsonSchema

from camp_agent.domain.faults import FaultType, OpenReport
from camp_agent.domain.guest_status import QuickPick
from camp_agent.domain.routing import Category, Route, Team, Urgency
from camp_agent.guide.port import GuideSection


class LlmError(Exception):
    pass


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


def _camp_clock(value: dt.time | None) -> dt.time | None:
    if value is not None and value.tzinfo is not None:
        raise ValueError("time must be HH:MM on the camp clock, with no zone")
    return value


# The default schema is RFC 3339 format "time", which requires a zone, so the model adds "Z".
type CampClockTime = Annotated[
    dt.time | None,
    AfterValidator(_camp_clock),
    WithJsonSchema(
        {
            "anyOf": [
                {"type": "string", "pattern": "^([01][0-9]|2[0-3]):[0-5][0-9]$"},
                {"type": "null"},
            ]
        }
    ),
]


class TableArgs(BaseModel):
    tool: str
    cabin: str
    party: int | None
    date: dt.date | None
    time: CampClockTime


@dataclass(frozen=True)
class TableBrief:
    request: str
    cabin: str
    today: dt.date
    stay_from: dt.date
    stay_to: dt.date
    rejected_for: tuple[str, ...] = ()


class LlmPort(Protocol):
    async def verify(self, text: str) -> Verdict: ...

    async def split(self, text: str) -> list[str]: ...

    async def classify(self, intent: str, hint: QuickPick | None = None) -> Classification: ...

    async def answer(self, question: str, sections: Sequence[GuideSection]) -> GuideAnswer: ...

    async def same_problem(self, fault: str, earlier: Sequence[OpenReport]) -> SameProblem: ...

    async def draft_ticket(self, team: Team, brief: TicketBrief) -> TicketArgs: ...

    async def draft_table(self, brief: TableBrief) -> TableArgs: ...

from dataclasses import dataclass
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncEngine

from camp_agent.db.cases import CaseRecord, CaseRepository
from camp_agent.db.reports import ReportRepository
from camp_agent.db.tasks import AnsweredQuestion, TaskRepository
from camp_agent.domain.faults import Confirmation, batch_of
from camp_agent.domain.guest_status import (
    booking_status,
    same_question,
    split_question,
    table_line,
    ticket_status,
)
from camp_agent.domain.routing import TaskState, specialist_for


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


class FindCase:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    # A closed case is still shown: its last status is what the guest came back to read.
    async def __call__(self, case_token: str) -> CaseRecord | None:
        async with self._engine.connect() as conn:
            return await CaseRepository(conn).find_by_token(case_token)

    # The case a returning guest may add to (D4). A closed case is never offered.
    async def open(self, case_token: str) -> CaseRecord | None:
        async with self._engine.connect() as conn:
            return await CaseRepository(conn).find_open_by_token(case_token)


class ListAnswers:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def __call__(self, case_id: int) -> list[AnsweredQuestion]:
        async with self._engine.connect() as conn:
            return await TaskRepository(conn).answers(case_id)


class ListBookings:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def __call__(self, case_id: int) -> list[BookingLine]:
        async with self._engine.connect() as conn:
            requests = await TaskRepository(conn).booking_requests(case_id)
        return [
            BookingLine(
                table_line(request.booking.party, request.booking.day, request.booking.at),
                booking_status(request.state, request.booking.party, request.booking.at),
            )
            for request in requests
        ]


class ListDeclined:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def __call__(self, case_id: int) -> list[str]:
        async with self._engine.connect() as conn:
            return await TaskRepository(conn).rejected(case_id)


class ListFaults:
    def __init__(self, engine: AsyncEngine, camp_timezone: ZoneInfo) -> None:
        self._engine = engine
        self._tz = camp_timezone

    async def __call__(self, case_id: int) -> CaseFaults:
        tickets: list[TicketLine] = []
        questions: list[QuestionView] = []
        split: dict[str, list[str]] = {}
        async with self._engine.connect() as conn:
            for fault in await TaskRepository(conn).faults(case_id):
                team = specialist_for(fault.category)
                if fault.state is TaskState.TICKETED and team is not None:
                    tickets.append(
                        TicketLine(fault.summary, ticket_status(team, fault.ticket_status))
                    )
                elif fault.state is TaskState.AWAITING_SPLIT:
                    split.setdefault(batch_of(fault.step_id), []).append(fault.summary)
                elif fault.state is TaskState.AWAITING_SAME and fault.same_report_id is not None:
                    earlier = await ReportRepository(conn).get(fault.same_report_id)
                    at = f"{earlier.at.astimezone(self._tz):%H:%M}"
                    text = same_question(earlier.fault_type, at)
                    questions.append(QuestionView(Confirmation.SAME, fault.step_id, text))
        questions[:0] = [
            QuestionView(Confirmation.SPLIT, batch, split_question(summaries))
            for batch, summaries in split.items()
        ]
        return CaseFaults(tickets, questions)

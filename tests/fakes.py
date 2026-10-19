from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from camp_agent.config import Settings
from camp_agent.domain.audit_entry import AuditEntry
from camp_agent.domain.cabin_reports import OpenReport, ReportDraft, SavedReport
from camp_agent.domain.case_status import CaseStatus
from camp_agent.domain.fault_flow import FaultTask
from camp_agent.domain.fault_type import FaultType
from camp_agent.domain.route_guard import Category, Route, TaskKind, TaskState
from camp_agent.domain.scope import Scope
from camp_agent.domain.specialist import Team
from camp_agent.domain.table_flow import TableBooking, TableTask
from camp_agent.domain.ticket_status import CLOSED_TICKET_STATES, TicketStatus
from camp_agent.domain.urgency import Urgency
from camp_agent.graph.stale_case_error import StaleCaseError
from camp_agent.graph.triage_types import (
    CaseSnapshot,
    LinkTarget,
    StatusChange,
    StepRecord,
    TaskAnswer,
    TaskDraft,
    TicketLink,
    ValidationRecord,
    WaitingTask,
)
from camp_agent.guide.guide_error import GuideError
from camp_agent.guide.guide_port import GuidePort
from camp_agent.guide.guide_types import GuideSection
from camp_agent.guide.markdown_guide import MarkdownGuide, parse_guide
from camp_agent.llm.llm_error import LlmError
from camp_agent.llm.llm_types import (
    Classification,
    GuideAnswer,
    SameProblem,
    TableArgs,
    TableBrief,
    TicketArgs,
    TicketBrief,
    Verdict,
)
from camp_agent.stay.seed_stays import SeedStays
from camp_agent.stay.stay_error import StayError
from camp_agent.stay.stay_port import StayContextPort
from camp_agent.stay.stay_types import Booking
from camp_agent.ticket.ticket_error import TicketError
from camp_agent.ticket.ticket_types import TicketKey, TicketReceipt, TicketRequest

CAMP_TZ = ZoneInfo("Europe/London")
QUESTION = Classification(
    category=Category.INFORMATION, route=Route.QUESTION, urgency=Urgency.NORMAL
)
NO_ANSWER = GuideAnswer(text="", section_id=None)


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def today(self) -> date:
        return self._now.astimezone(CAMP_TZ).date()

    def advance(self, delta: timedelta) -> None:
        self._now += delta


def oct_19(hour: int = 14) -> FakeClock:
    return FakeClock(datetime(2026, 10, 19, hour, tzinfo=CAMP_TZ).astimezone(UTC))


class SwitchableGuide:
    def __init__(self, inner: GuidePort) -> None:
        self._inner = inner
        self.down = False

    async def search(self, question: str) -> list[GuideSection]:
        self._check()
        return await self._inner.search(question)

    async def section(self, section_id: str) -> GuideSection | None:
        self._check()
        return await self._inner.section(section_id)

    def _check(self) -> None:
        if self.down:
            raise GuideError("down")


def demo_guide() -> SwitchableGuide:
    return SwitchableGuide(MarkdownGuide(Settings().guide_path))


def demo_section(section_id: str) -> GuideSection:
    return parse_guide(Settings().guide_path.read_text(encoding="utf-8"))[section_id]


class FakeLlm:
    def __init__(
        self,
        verdicts: dict[str, Verdict] | None = None,
        splits: dict[str, list[str]] | None = None,
        classes: dict[str, Classification] | None = None,
        answers: dict[str, GuideAnswer] | None = None,
        same: dict[str, int] | None = None,
        drafts: dict[str, list[TicketArgs]] | None = None,
        tables: dict[str, list[TableArgs]] | None = None,
        down: bool = False,
    ) -> None:
        self._verdicts = verdicts or {}
        self._splits = splits or {}
        self._classes = classes or {}
        self._answers = answers or {}
        self._same = same or {}
        self._drafts = drafts or {}
        self._tables = tables or {}
        self._down = down
        self.down_for: set[str] = set()
        self.briefs: list[TicketBrief] = []
        self.table_briefs: list[TableBrief] = []
        self.calls: list[str] = []
        self.inputs: list[str] = []
        self.offered: list[str] = []

    async def verify(self, text: str) -> Verdict:
        self._call("verify", text)
        return self._verdicts.get(text, Verdict.GENUINE)

    async def split(self, text: str) -> list[str]:
        self._call("split", text)
        return self._splits.get(text, [text])

    async def classify(self, intent: str) -> Classification:
        self._call("classify", intent)
        return self._classes.get(intent, QUESTION)

    async def answer(self, question: str, sections: Sequence[GuideSection]) -> GuideAnswer:
        self._call("answer", question, *(section.body for section in sections))
        self.offered = [section.id for section in sections]
        return self._answers.get(question, NO_ANSWER)

    async def same_problem(self, fault: str, earlier: Sequence[OpenReport]) -> SameProblem:
        self._call("same_problem", fault, *(report.summary for report in earlier))
        return SameProblem(report_id=self._same.get(fault))

    async def draft_ticket(self, team: Team, brief: TicketBrief) -> TicketArgs:
        self._call("draft_ticket", brief.fault)
        self.briefs.append(brief)
        queued = self._drafts.get(brief.fault)
        if queued:
            return queued.pop(0)
        return TicketArgs(tool="create_ticket", cabin=brief.cabin, summary=brief.fault)

    async def draft_table(self, brief: TableBrief) -> TableArgs:
        self._call("draft_table", brief.request)
        self.table_briefs.append(brief)
        queued = self._tables.get(brief.request)
        if queued:
            return queued.pop(0)
        return table_args(brief.cabin, brief.today)

    def _call(self, name: str, *inputs: str) -> None:
        self.calls.append(name)
        self.inputs.extend(inputs)
        if self._down or name in self.down_for:
            raise LlmError("down")


def table_args(
    cabin: str = "C12", day: date | None = date(2026, 10, 19), party: int | None = 4
) -> TableArgs:
    return TableArgs(tool="request_table", cabin=cabin, party=party, date=day, time=time(19, 30))


class SwitchableStays:
    def __init__(self, inner: StayContextPort) -> None:
        self._inner = inner
        self.down = False
        self.lookups = 0

    async def find_booking(self, booking_ref: str) -> Booking | None:
        self.lookups += 1
        if self.down:
            raise StayError("down")
        return await self._inner.find_booking(booking_ref)


def demo_stays() -> SwitchableStays:
    return SwitchableStays(SeedStays(Settings().stays_path))


class FakeTickets:
    def __init__(self) -> None:
        self.created: dict[TicketKey, TicketRequest] = {}
        self.calls = 0
        self.down = False

    async def create(self, request: TicketRequest) -> TicketReceipt:
        self.calls += 1
        if self.down:
            raise TicketError("down")
        self.created.setdefault(request.key, request)
        ref = f"T{list(self.created).index(request.key) + 1}"
        return TicketReceipt(ref, TicketStatus.OPEN, 1)


class InMemoryTriageStore:
    def __init__(self) -> None:
        self.cases: dict[int, CaseSnapshot] = {}
        self.tasks: list[TaskDraft] = []
        self.answers: list[TaskAnswer] = []
        self.audit: list[AuditEntry] = []
        self.tickets: dict[str, TicketLink] = {}
        self.same: dict[str, int] = {}
        self.validations: list[ValidationRecord] = []
        self.bookings: dict[str, TableBooking] = {}
        self.reports: list[tuple[ReportDraft, SavedReport]] = []

    def add_case(self, case_id: int, scope: Scope | None = None) -> None:
        self.cases[case_id] = CaseSnapshot(CaseStatus(), scope, 0)

    async def load(self, case_id: int) -> CaseSnapshot:
        return self.cases[case_id]

    async def commit(self, case_id: int, step: StepRecord) -> None:
        if step.status is not None:
            self.write_status(case_id, step.status)
        known = {task.step_id for task in self.tasks}
        self.tasks.extend(task for task in step.tasks if task.step_id not in known)
        self.answers.extend(step.answers)
        for move in step.transitions:
            for i, task in enumerate(self.tasks):
                if task.step_id == move.step_id and task.state is move.expected:
                    self.tasks[i] = replace(task, state=move.state, kind=move.kind or task.kind)
                    if move.ticket is not None:
                        self.tickets[task.step_id] = move.ticket
                    if move.same_report_id is not None:
                        self.same[task.step_id] = move.same_report_id
                    if move.booking is not None:
                        self.bookings[task.step_id] = move.booking
        if step.validation is not None:
            self.validations.append(step.validation)
        self.audit.append(step.audit)

    @asynccontextmanager
    async def lock_case(self, case_id: int) -> AsyncIterator["InMemoryLockedCase"]:
        yield InMemoryLockedCase(self, case_id)

    async def task_states(self, case_id: int) -> list[TaskState]:
        return [task.state for task in self.tasks]

    async def faults(self, case_id: int) -> list[FaultTask]:
        return [
            FaultTask(
                task.step_id,
                task.state,
                task.category or Category.OTHER,
                task.fault_type or FaultType.OTHER,
                task.urgency,
                task.summary,
                self.same.get(task.step_id),
            )
            for task in self.tasks
            if task.kind is TaskKind.FAULT
        ]

    async def tables(self, case_id: int) -> list[TableTask]:
        return [
            TableTask(task.step_id, task.state, task.summary)
            for task in self.tasks
            if task.kind is TaskKind.TABLE
        ]

    async def save_report(self, case_id: int, draft: ReportDraft) -> SavedReport:
        for saved_draft, saved in self.reports:
            if saved_draft.step_id == draft.step_id:
                return saved
        earlier = tuple(
            OpenReport(saved.id, saved_draft.fault_type, saved_draft.summary, saved_draft.at)
            for saved_draft, saved in self.reports
            if saved_draft.cabin == draft.cabin and self._open(saved_draft.step_id)
        )
        saved = SavedReport(len(self.reports) + 1, earlier)
        self.reports.append((draft, saved))
        return saved

    async def link_target(self, report_id: int) -> LinkTarget | None:
        for draft, saved in self.reports:
            if saved.id == report_id:
                ticket = self.tickets.get(draft.step_id)
                if ticket is None:
                    return LinkTarget(None, None, None, None)
                return LinkTarget(ticket.ref, ticket.status, ticket.version, ticket.cabin)
        return None

    def add_report(self, draft: ReportDraft, ticket: TicketLink | None) -> int:
        report_id = len(self.reports) + 1
        self.reports.append((draft, SavedReport(report_id, ())))
        if ticket is not None:
            self.tickets[draft.step_id] = ticket
        return report_id

    def _open(self, step_id: str) -> bool:
        ticket = self.tickets.get(step_id)
        return ticket is None or ticket.status not in CLOSED_TICKET_STATES

    async def awaiting_scope(self, case_id: int) -> list[WaitingTask]:
        return [
            WaitingTask(task.step_id, task.kind, task.category, task.summary)
            for task in self.tasks
            if task.state is TaskState.AWAITING_SCOPE and task.category is not None
        ]

    def write_status(self, case_id: int, change: StatusChange) -> None:
        case = self.cases[case_id]
        if change.version != case.version:
            raise StaleCaseError(case_id)
        self.cases[case_id] = replace(case, status=change.status, version=case.version + 1)

    def status(self, case_id: int) -> CaseStatus:
        return self.cases[case_id].status


class InMemoryLockedCase:
    def __init__(self, store: InMemoryTriageStore, case_id: int) -> None:
        self._store = store
        self._case_id = case_id
        self.case = store.cases[case_id]

    async def commit(self, step: StepRecord) -> None:
        await self._store.commit(self._case_id, step)

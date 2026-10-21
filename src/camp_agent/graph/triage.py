from collections.abc import Mapping, Set
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, TypedDict
from zoneinfo import ZoneInfo

from camp_agent.domain.arg_validation import ValidationOutcome
from camp_agent.domain.cases import AuditEntry, CaseStatus, StateReason
from camp_agent.domain.faults import FaultTask, FaultType, ReportDraft, SavedReport, TicketStatus
from camp_agent.domain.guest_status import QuickPick
from camp_agent.domain.routing import Category, Scope, TaskKind, TaskState, Urgency
from camp_agent.domain.safety import SafetyRule
from camp_agent.domain.table_bookings import TableBooking, TableTask
from camp_agent.llm.port import Classification


class StaleCaseError(Exception):
    pass


@dataclass(frozen=True)
class StatusChange:
    status: CaseStatus
    version: int


@dataclass(frozen=True)
class CaseSnapshot:
    status: CaseStatus
    scope: Scope | None
    version: int

    def change(self, status: CaseStatus) -> StatusChange:
        return StatusChange(status, self.version)


@dataclass(frozen=True)
class TaskDraft:
    step_id: str
    kind: TaskKind
    category: Category | None
    urgency: Urgency
    state: TaskState
    summary: str
    fault_type: FaultType | None = None


@dataclass(frozen=True)
class TaskAnswer:
    step_id: str
    text: str
    section_id: str | None


@dataclass(frozen=True)
class WaitingTask:
    step_id: str
    kind: TaskKind
    category: Category
    summary: str


@dataclass(frozen=True)
class TicketLink:
    ref: str
    status: TicketStatus
    version: int
    cabin: str


@dataclass(frozen=True)
class LinkTarget:
    ticket_ref: str | None
    ticket_status: TicketStatus | None
    ticket_version: int | None
    cabin: str | None


@dataclass(frozen=True)
class TaskTransition:
    step_id: str
    state: TaskState
    # The move applies only while the task is still in this state.
    expected: TaskState
    same_report_id: int | None = None
    ticket: TicketLink | None = None
    booking: TableBooking | None = None
    # Set when the route changes the task's kind: a request with no active stay (D19).
    kind: TaskKind | None = None


@dataclass(frozen=True)
class ValidationRecord:
    step_id: str
    outcome: ValidationOutcome
    args: Mapping[str, str | int | None]


@dataclass(frozen=True)
class TaskHold:
    step_id: str
    expected: TaskState
    reason: StateReason
    audit: AuditEntry
    record: ValidationRecord | None = None


@dataclass(frozen=True)
class StepRecord:
    audit: AuditEntry
    status: StatusChange | None = None
    tasks: tuple[TaskDraft, ...] = ()
    answers: tuple[TaskAnswer, ...] = ()
    transitions: tuple[TaskTransition, ...] = ()
    validation: ValidationRecord | None = None


@dataclass(frozen=True)
class TriagePolicy:
    safety: SafetyRule
    held_categories: Set[str]
    clarify_max_rounds: int
    camp_timezone: ZoneInfo


class LockedCase(Protocol):
    case: CaseSnapshot

    async def commit(self, step: StepRecord) -> None: ...


class TriageStore(Protocol):
    async def load(self, case_id: int) -> CaseSnapshot: ...

    async def awaiting_scope(self, case_id: int) -> list[WaitingTask]: ...

    async def faults(self, case_id: int) -> list[FaultTask]: ...

    async def tables(self, case_id: int) -> list[TableTask]: ...

    async def task_states(self, case_id: int) -> list[TaskState]: ...

    # One step of the CabinReports aggregate: the report records every open report in its cabin
    # that it was checked against (I4). A repeat step id returns the report already saved.
    async def save_report(self, case_id: int, draft: ReportDraft) -> SavedReport: ...

    async def link_target(self, report_id: int) -> LinkTarget | None: ...

    # Holds the case row from the read to the commit, so no status write lands in between.
    def lock_case(self, case_id: int) -> AbstractAsyncContextManager[LockedCase]: ...

    # Locks the case row, reads every task and closes the case when all are done (D20, I11),
    # in one transaction.
    async def close_if_done(self, case_id: int, now: datetime) -> None: ...

    # One graph step: the case changes, its tasks and its audit entry in one transaction (I13).
    # Raises StaleCaseError when the case changed since the status was computed.
    async def commit(self, case_id: int, step: StepRecord) -> None: ...


@dataclass(frozen=True)
class PendingMessage:
    id: int
    text: str
    # Queued again by a staff restore of a spam park: the spam verdict is overridden (D33).
    restored: bool = False
    # The topic tapped with a new request: a hint for classify, never the route (D51).
    pick: QuickPick | None = None


class BatchOutcome(StrEnum):
    TRIAGED = "triaged"
    # The batch stopped on a parked case; a staff restore queues it again.
    PARKED = "parked"


class TriageGraph(Protocol):
    async def run(self, case_id: int, batch: list[PendingMessage]) -> BatchOutcome: ...

    # Tasks that waited for scope go on once the case has it (D2).
    async def resume(self, case_id: int) -> None: ...


def next_batch(pending: list[PendingMessage]) -> list[PendingMessage]:
    # Restored messages run on their own, so the spam override never covers a new message.
    restored = pending[0].restored
    batch: list[PendingMessage] = []
    for message in pending:
        if message.restored is not restored:
            break
        batch.append(message)
    return batch


SAFETY = "safety"
VERIFY = "verify"
PARK = "park"
CLARIFY = "clarify"
SPLIT = "split"
CLASSIFY = "classify"
ROUTE_GUARD = "route_guard"
ANSWER = "answer"
LLM_FAILED = "llm_failed"
CONFIRM_SPLIT = "confirm_split"
REPORT = "report"
SAME = "same"
SPECIALIST = "specialist"
LINK = "link"
BOOKING = "booking"
DISPATCH = "dispatch"


class TriageState(TypedDict):
    case_id: int
    batch_key: str
    text: str
    intents: list[str]
    index: int
    classification: Classification | None
    failed_step: str
    next: str
    fault: str
    table: str
    drafts: int
    rejected_for: list[str]
    report: SavedReport | None
    restored: bool
    pick: QuickPick | None
    parked: bool


class TriageUpdate(TypedDict, total=False):
    intents: list[str]
    index: int
    classification: Classification | None
    failed_step: str
    next: str
    fault: str
    table: str
    drafts: int
    rejected_for: list[str]
    report: SavedReport | None
    parked: bool


def start_state(
    case_id: int,
    batch_key: str,
    text: str,
    entry: str,
    restored: bool = False,
    pick: QuickPick | None = None,
) -> TriageState:
    return {
        "case_id": case_id,
        "batch_key": batch_key,
        "text": text,
        "intents": [],
        "index": 0,
        "classification": None,
        "failed_step": "",
        "next": entry,
        "fault": "",
        "table": "",
        "drafts": 0,
        "rejected_for": [],
        "report": None,
        "restored": restored,
        "pick": pick,
        "parked": False,
    }


async def hold_task(
    store: TriageStore,
    case_id: int,
    hold: TaskHold,
    now: datetime,
    case: CaseSnapshot | None = None,
) -> None:
    # The task leaves the actionable states, so no later run retries it on its own.
    case = case or await store.load(case_id)
    status = case.status.hold(hold.reason, now)
    move = TaskTransition(hold.step_id, TaskState.HELD, hold.expected)
    step = StepRecord(hold.audit, case.change(status), transitions=(move,), validation=hold.record)
    await store.commit(case_id, step)


def required_scope(case: CaseSnapshot) -> Scope:
    # A fault or a table reaches its desk only once the route guard saw a scope (D19).
    if case.scope is None:
        raise RuntimeError("a task without a scope reached its desk")
    return case.scope

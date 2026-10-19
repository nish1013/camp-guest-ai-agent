from collections.abc import Mapping, Set
from dataclasses import dataclass

from camp_agent.domain.arg_validation import ValidationOutcome
from camp_agent.domain.audit_entry import AuditEntry
from camp_agent.domain.case_status import CaseStatus
from camp_agent.domain.fault_type import FaultType
from camp_agent.domain.route_guard import Category, TaskKind, TaskState
from camp_agent.domain.safety_rule import SafetyRule
from camp_agent.domain.scope import Scope
from camp_agent.domain.ticket_status import TicketStatus
from camp_agent.domain.urgency import Urgency


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


@dataclass(frozen=True)
class ValidationRecord:
    step_id: str
    outcome: ValidationOutcome
    args: Mapping[str, str]


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

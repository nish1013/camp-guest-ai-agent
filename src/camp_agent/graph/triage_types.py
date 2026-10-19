from collections.abc import Set
from dataclasses import dataclass

from camp_agent.domain.audit_entry import AuditEntry
from camp_agent.domain.case_status import CaseStatus
from camp_agent.domain.route_guard import Category, TaskKind, TaskState
from camp_agent.domain.safety_rule import SafetyRule
from camp_agent.domain.scope import Scope
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
class TaskTransition:
    step_id: str
    state: TaskState


@dataclass(frozen=True)
class StepRecord:
    audit: AuditEntry
    status: StatusChange | None = None
    tasks: tuple[TaskDraft, ...] = ()
    answers: tuple[TaskAnswer, ...] = ()
    resumed: tuple[TaskTransition, ...] = ()


@dataclass(frozen=True)
class TriagePolicy:
    safety: SafetyRule
    held_categories: Set[str]
    clarify_max_rounds: int

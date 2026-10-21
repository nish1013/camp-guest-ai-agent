from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from camp_agent.domain.faults import CLOSED_TICKET_STATES, TicketStatus
from camp_agent.domain.routing import TaskState, Urgency, higher_urgency, urgency_rank

type AuditValue = str | int | list[str]


@dataclass(frozen=True)
class AuditEntry:
    step: str
    decision: str
    detail: Mapping[str, AuditValue] = field(default_factory=dict)


class CaseState(StrEnum):
    OPEN = "open"
    HELD = "held"
    PARKED = "parked"
    CLOSED = "closed"


class StateReason(StrEnum):
    EMERGENCY = "emergency"
    MONEY = "money"
    LLM_FAILED = "llm_failed"
    CLARIFY_LIMIT = "clarify_limit"
    FAULT_REVIEW = "fault_review"
    TICKETING_DOWN = "ticketing_down"
    BOOKING_REVIEW = "booking_review"
    SPAM = "spam"
    VERIFICATION = "verification"


LIVE_STATES = frozenset({CaseState.OPEN, CaseState.HELD, CaseState.PARKED})


@dataclass(frozen=True)
class CaseStatus:
    state: CaseState = CaseState.OPEN
    reason: StateReason | None = None
    safety: bool = False
    urgency: Urgency = Urgency.NORMAL
    clarify_rounds: int = 0
    held_at: datetime | None = None
    closed_at: datetime | None = None

    def emergency(self, now: datetime) -> "CaseStatus":
        return replace(
            self,
            state=CaseState.HELD,
            reason=StateReason.EMERGENCY,
            safety=True,
            urgency=Urgency.URGENT,
            held_at=self.held_at or now,
            closed_at=None,
        )

    def hold(self, reason: StateReason, now: datetime) -> "CaseStatus":
        # A parked case leaves parking only by a safety hit or a staff restore (I10).
        if self.state is not CaseState.OPEN:
            return self
        return replace(self, state=CaseState.HELD, reason=reason, held_at=now)

    def park(self, reason: StateReason) -> "CaseStatus":
        # Held work stays with staff, and a safety case is never parked (I9).
        if self.state is not CaseState.OPEN or self.safety:
            return self
        return replace(self, state=CaseState.PARKED, reason=reason)

    def park_unverified(self) -> "CaseStatus":
        # Failed verification parks held work too (I10); only a safety case stays held (I9).
        if self.safety:
            return self
        return replace(self, state=CaseState.PARKED, reason=StateReason.VERIFICATION, held_at=None)

    def clarify(self, max_rounds: int, now: datetime) -> "CaseStatus":
        if self.clarify_rounds >= max_rounds:
            return self.hold(StateReason.CLARIFY_LIMIT, now)
        return replace(self, clarify_rounds=self.clarify_rounds + 1)

    def understood(self) -> "CaseStatus":
        return replace(self, clarify_rounds=0)

    def restore(self, held: StateReason | None, now: datetime) -> "CaseStatus":
        # A staff restore ends the park (D33); work still held goes back to staff.
        if self.state is not CaseState.PARKED:
            return self
        if held is None:
            return replace(self, state=CaseState.OPEN, reason=None, held_at=None)
        return replace(self, state=CaseState.HELD, reason=held, held_at=now)

    def release(self) -> "CaseStatus":
        # Staff settled the hold; the clarify count starts again for the next message.
        if self.state is not CaseState.HELD:
            return self
        return replace(self, state=CaseState.OPEN, reason=None, held_at=None, clarify_rounds=0)

    def close(self, now: datetime) -> "CaseStatus":
        return replace(
            self,
            state=CaseState.CLOSED,
            reason=None,
            clarify_rounds=0,
            held_at=None,
            closed_at=now,
        )

    def reopen(self) -> "CaseStatus":
        if self.state is not CaseState.CLOSED:
            return self
        return replace(self, state=CaseState.OPEN, closed_at=None)

    def raise_urgency(self, urgency: Urgency) -> "CaseStatus":
        return replace(self, urgency=higher_urgency(self.urgency, urgency))


_ACTED = frozenset({TaskState.TICKETED, TaskState.BOOKING_REQUESTED})
_ASKING = frozenset({TaskState.AWAITING_SCOPE, TaskState.AWAITING_SPLIT, TaskState.AWAITING_SAME})


def in_action(task_states: Collection[TaskState]) -> bool:
    return not _ACTED.isdisjoint(task_states)


def asks_guest(status: CaseStatus, task_states: Collection[TaskState]) -> bool:
    clarifying = status.state is CaseState.OPEN and status.clarify_rounds > 0
    return clarifying or not _ASKING.isdisjoint(task_states)


def triages_follow_up(status: CaseStatus, task_states: Collection[TaskState]) -> bool:
    # A case in action takes new messages for staff to read; only an open question is triaged.
    return not in_action(task_states) or asks_guest(status, task_states)


_FINISHED = frozenset(
    {
        TaskState.DONE,
        TaskState.BOOKING_CONFIRMED,
        TaskState.BOOKING_DECLINED,
        TaskState.REJECTED,
    }
)


@dataclass(frozen=True)
class TaskProgress:
    state: TaskState
    ticket_status: TicketStatus | None


def finished(task: TaskProgress) -> bool:
    if task.state is TaskState.TICKETED:
        return task.ticket_status in CLOSED_TICKET_STATES
    return task.state in _FINISHED


def settled(status: CaseStatus, tasks: Sequence[TaskProgress], now: datetime) -> CaseStatus:
    # A closed case has no open task (I11): open work reopens it, and the last task done
    # closes it (D20). A held or parked case waits for staff; a question to the guest waits too.
    open_work = not all(finished(task) for task in tasks)
    if status.state is CaseState.CLOSED:
        return status.reopen() if open_work else status
    if status.state is CaseState.OPEN and not open_work and status.clarify_rounds == 0:
        return status.close(now)
    return status


def reopens(closed_at: datetime | None, now: datetime, window: timedelta) -> bool:
    return closed_at is not None and now - closed_at < window


def queue_rank(urgency: Urgency, overdue: bool, created_at: datetime) -> tuple[int, bool, datetime]:
    # Urgency orders the view (D8); within one urgency an overdue case goes first (D11).
    return (-urgency_rank(urgency), not overdue, created_at)


def run_active(lease_until: datetime | None, now: datetime) -> bool:
    # The same test as the claim: a lease at or before now is free (I2).
    return lease_until is not None and lease_until > now


@dataclass(frozen=True)
class DeskHours:
    opens: time
    closes: time
    tz: ZoneInfo

    def __post_init__(self) -> None:
        if self.opens >= self.closes:
            raise ValueError("the desk must open before it closes")

    def is_open(self, at: datetime) -> bool:
        local = at.astimezone(self.tz).time()
        return self.opens <= local < self.closes

    def staffed_between(self, start: datetime, end: datetime) -> timedelta:
        staffed = timedelta()
        day = start.astimezone(self.tz).date()
        last = end.astimezone(self.tz).date()
        while day <= last:
            opens = datetime.combine(day, self.opens, self.tz)
            closes = datetime.combine(day, self.closes, self.tz)
            overlap = min(end, closes) - max(start, opens)
            staffed += max(overlap, timedelta())
            day += timedelta(days=1)
        return staffed


def is_overdue(held_at: datetime | None, now: datetime, desk: DeskHours, gate: timedelta) -> bool:
    # Only staffed time counts: a case held at night starts its clock at opening (D30).
    return held_at is not None and desk.staffed_between(held_at, now) >= gate

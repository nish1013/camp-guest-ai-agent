from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from camp_agent.domain.case_state import CaseState
from camp_agent.domain.case_status import CaseStatus
from camp_agent.domain.route_guard import TaskState
from camp_agent.domain.ticket_status import CLOSED_TICKET_STATES, TicketStatus

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

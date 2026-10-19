from datetime import UTC, datetime, timedelta

import pytest

from camp_agent.domain.case_closure import TaskProgress, finished, reopens, settled
from camp_agent.domain.case_state import CaseState, StateReason
from camp_agent.domain.case_status import CaseStatus
from camp_agent.domain.route_guard import TaskState
from camp_agent.domain.ticket_status import TicketStatus

NOW = datetime(2026, 10, 19, 14, tzinfo=UTC)
DAY = timedelta(hours=24)
T7_OPEN = TaskProgress(TaskState.TICKETED, TicketStatus.OPEN)
T7_DONE = TaskProgress(TaskState.TICKETED, TicketStatus.DONE)
BOOKED = TaskProgress(TaskState.BOOKING_CONFIRMED, None)
WAITING = TaskProgress(TaskState.BOOKING_REQUESTED, None)
CLOSED = CaseStatus().close(NOW - timedelta(hours=1))


@pytest.mark.parametrize(
    ("task", "done"),
    [
        (T7_OPEN, False),
        (TaskProgress(TaskState.TICKETED, TicketStatus.IN_PROGRESS), False),
        (T7_DONE, True),
        (TaskProgress(TaskState.TICKETED, TicketStatus.CANCELLED), True),
        (BOOKED, True),
        (TaskProgress(TaskState.BOOKING_DECLINED, None), True),
        (WAITING, False),
        (TaskProgress(TaskState.DONE, None), True),
        (TaskProgress(TaskState.HELD, None), False),
        (TaskProgress(TaskState.AWAITING_SCOPE, None), False),
    ],
)
def test_d20_finished_tasks(task: TaskProgress, done: bool) -> None:
    assert finished(task) is done


def test_i11_last_task_done_closes() -> None:
    status = settled(CaseStatus(), [T7_DONE, BOOKED], NOW)

    assert status.state is CaseState.CLOSED
    assert status.closed_at == NOW


def test_i11_open_task_keeps_case_open() -> None:
    assert settled(CaseStatus(), [T7_DONE, WAITING], NOW).state is CaseState.OPEN


def test_i11_question_to_guest_keeps_open() -> None:
    clarifying = CaseStatus(clarify_rounds=1)

    assert settled(clarifying, [T7_DONE], NOW) == clarifying


@pytest.mark.parametrize(
    "status",
    [CaseStatus().hold(StateReason.MONEY, NOW), CaseStatus().park(StateReason.SPAM)],
    ids=["held", "parked"],
)
def test_d20_held_or_parked_not_closed(status: CaseStatus) -> None:
    assert settled(status, [T7_DONE], NOW) == status


def test_i11_open_work_reopens_closed() -> None:
    status = settled(CLOSED, [T7_OPEN], NOW)

    assert status.state is CaseState.OPEN
    assert status.closed_at is None


def test_i11_closed_stays_closed_when_done() -> None:
    assert settled(CLOSED, [T7_DONE], NOW) == CLOSED


@pytest.mark.parametrize(
    ("closed_ago", "reopen"),
    [(timedelta(hours=3), True), (DAY - timedelta(seconds=1), True), (DAY, False)],
    ids=["3h", "23:59:59", "24h"],
)
def test_d20_reply_window(closed_ago: timedelta, reopen: bool) -> None:
    assert reopens(NOW - closed_ago, NOW, DAY) is reopen


def test_d20_open_case_never_reopens() -> None:
    assert not reopens(None, NOW, DAY)

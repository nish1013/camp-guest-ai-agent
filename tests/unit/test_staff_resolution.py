from datetime import UTC, datetime

import pytest

from camp_agent.domain.cases import CaseState, CaseStatus, StateReason
from camp_agent.domain.routing import Category, TaskKind, TaskState
from camp_agent.domain.staff_resolution import approved_state, edit_errors

NOW = datetime(2026, 10, 19, 14, tzinfo=UTC)


@pytest.mark.parametrize(
    ("kind", "reported", "state"),
    [
        (TaskKind.FAULT, True, TaskState.DRAFTING),
        (TaskKind.FAULT, False, TaskState.SPLIT_CONFIRMED),
        (TaskKind.TABLE, False, TaskState.QUEUED),
        (TaskKind.MONEY, False, TaskState.DONE),
        (TaskKind.EMERGENCY, False, TaskState.DONE),
        (TaskKind.QUESTION, False, TaskState.DONE),
    ],
)
def test_us12_approved_task_lane(kind: TaskKind, reported: bool, state: TaskState) -> None:
    assert approved_state(kind, reported) is state


@pytest.mark.parametrize(
    ("kind", "category", "edited", "errors"),
    [
        (TaskKind.FAULT, Category.HOUSEKEEPING, True, 0),
        (TaskKind.FAULT, None, True, 0),
        (TaskKind.FAULT, Category.REFUND, True, 1),
        (TaskKind.MONEY, None, True, 1),
        (TaskKind.MONEY, None, False, 0),
    ],
)
def test_d31_only_fault_action_edited(
    kind: TaskKind, category: Category | None, edited: bool, errors: int
) -> None:
    assert len(edit_errors(kind, category, edited)) == errors


def test_us12_release_resets_hold() -> None:
    held = CaseStatus(clarify_rounds=2).hold(StateReason.CLARIFY_LIMIT, NOW)

    released = held.release()

    assert (released.state, released.reason, released.held_at) == (CaseState.OPEN, None, None)
    assert released.clarify_rounds == 0


def test_us12_release_leaves_parked() -> None:
    parked = CaseStatus().park(StateReason.SPAM)

    assert parked.release() == parked

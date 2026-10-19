import pytest

from camp_agent.domain.arg_validation import (
    LinkDecision,
    ValidationOutcome,
    check_link,
    check_ticket_args,
)
from camp_agent.domain.fault_flow import (
    Confirmation,
    FaultTask,
    after_answer,
    answered,
    next_actionable,
    split_to_confirm,
)
from camp_agent.domain.fault_type import FaultType
from camp_agent.domain.guest_status import same_question, split_question
from camp_agent.domain.route_guard import Category, TaskState
from camp_agent.domain.ticket_status import TicketStatus
from camp_agent.domain.urgency import Urgency

QUEUED = TaskState.QUEUED
NORMAL = Urgency.NORMAL


def fault(step: str, state: TaskState = QUEUED, urgency: Urgency = NORMAL) -> FaultTask:
    return FaultTask(step, state, Category.MAINTENANCE, FaultType.HEATING, urgency, step)


@pytest.mark.parametrize(
    "tool, cabin, summary, reasons",
    [
        ("create_ticket", "C12", "Heater off", ()),
        ("create_ticket", "C14", "Heater off", ("cabin must be C12",)),
        ("create_ticket", "c12", "Heater off", ("cabin must be C12",)),
        ("issue_refund", "C12", "Heater off", ("tool must be create_ticket",)),
        ("create_ticket", "C12", "  ", ("summary must be 1 to 200 characters",)),
        ("create_ticket", "C12", "x" * 200, ()),
        ("create_ticket", "C12", "x" * 201, ("summary must be 1 to 200 characters",)),
    ],
    ids=["pass", "other-cabin", "cabin-case", "other-tool", "blank", "200-chars", "201-chars"],
)
def test_d15_ticket_args_checked(
    tool: str, cabin: str, summary: str, reasons: tuple[str, ...]
) -> None:
    check = check_ticket_args(tool, cabin, summary, "C12")

    expected = ValidationOutcome.BLOCK if reasons else ValidationOutcome.PASS
    assert (check.outcome, check.reasons) == (expected, reasons)


@pytest.mark.parametrize(
    "ref, status, cabin, decision",
    [
        ("T7", TicketStatus.OPEN, "C12", LinkDecision.LINK),
        ("T7", TicketStatus.IN_PROGRESS, "C12", LinkDecision.LINK),
        ("T7", TicketStatus.DONE, "C12", LinkDecision.NEW_TICKET),
        ("T7", TicketStatus.CANCELLED, "C12", LinkDecision.NEW_TICKET),
        (None, None, None, LinkDecision.HOLD),
        ("T7", TicketStatus.OPEN, "C14", LinkDecision.HOLD),
    ],
    ids=["open", "in-progress", "done", "cancelled", "no-ticket-yet", "other-cabin"],
)
def test_d38_link_checked(
    ref: str | None, status: TicketStatus | None, cabin: str | None, decision: LinkDecision
) -> None:
    assert check_link(ref, status, cabin, "C12").decision is decision


@pytest.mark.parametrize(
    "faults, asked",
    [
        ([fault("m1/t0"), fault("m1/t1")], [["m1/t0", "m1/t1"]]),
        ([fault("m1/t0"), fault("m1/t1", urgency=Urgency.URGENT)], []),
        ([fault("m1/t0")], []),
        ([fault("m1/t0"), fault("m2/t0")], []),
        ([fault("m1/t0"), fault("m1/t1", TaskState.SPLIT_CONFIRMED)], []),
        ([fault("m1/t0", TaskState.AWAITING_SCOPE), fault("m1/t1", TaskState.AWAITING_SCOPE)], []),
    ],
    ids=["two-normal", "one-urgent", "one", "two-messages", "one-confirmed", "no-scope"],
)
def test_d39_split_confirmed_first(faults: list[FaultTask], asked: list[list[str]]) -> None:
    groups = split_to_confirm(faults)

    assert [[f.step_id for f in group] for group in groups] == asked


@pytest.mark.parametrize(
    "state, picked",
    [
        (TaskState.QUEUED, True),
        (TaskState.SPLIT_CONFIRMED, True),
        (TaskState.DRAFTING, True),
        (TaskState.LINKING, True),
        (TaskState.AWAITING_SPLIT, False),
        (TaskState.AWAITING_SAME, False),
        (TaskState.AWAITING_SCOPE, False),
        (TaskState.HELD, False),
        (TaskState.TICKETED, False),
    ],
)
def test_us4_next_actionable(state: TaskState, picked: bool) -> None:
    task = fault("m1/t0", state)

    assert next_actionable([task]) == (task if picked else None)


def test_d39_split_answer_moves_its_message() -> None:
    waiting = [
        fault("m1/t0", TaskState.AWAITING_SPLIT),
        fault("m1/t1", TaskState.AWAITING_SPLIT),
        fault("m2/t0", TaskState.AWAITING_SPLIT),
    ]

    assert [f.step_id for f in answered(waiting, Confirmation.SPLIT, "m1")] == ["m1/t0", "m1/t1"]
    assert answered(waiting, Confirmation.SAME, "m1/t0") == []


@pytest.mark.parametrize(
    "confirmation, yes, state",
    [
        (Confirmation.SPLIT, True, TaskState.SPLIT_CONFIRMED),
        (Confirmation.SPLIT, False, TaskState.HELD),
        (Confirmation.SAME, True, TaskState.LINKING),
        (Confirmation.SAME, False, TaskState.DRAFTING),
    ],
)
def test_us4_answer_target(confirmation: Confirmation, yes: bool, state: TaskState) -> None:
    assert after_answer(confirmation, yes) is state


def test_us4_question_text() -> None:
    assert (
        split_question(["heater off", "tap leaking"])
        == "I found 2 issues: heater off, tap leaking. Correct?"
    )
    assert (
        same_question(FaultType.HOT_WATER, "14:05") == "Same problem as the 14:05 hot water report?"
    )

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from camp_agent.domain.fault_type import FaultType
from camp_agent.domain.route_guard import Category, TaskState
from camp_agent.domain.ticket_status import TicketStatus
from camp_agent.domain.urgency import Urgency

TO_REPORT = frozenset({TaskState.QUEUED, TaskState.SPLIT_CONFIRMED})
ACTIONABLE = TO_REPORT | {TaskState.DRAFTING, TaskState.LINKING}


@dataclass(frozen=True)
class FaultTask:
    step_id: str
    state: TaskState
    category: Category
    fault_type: FaultType
    urgency: Urgency
    summary: str
    same_report_id: int | None = None
    ticket_status: TicketStatus | None = None


def batch_of(step_id: str) -> str:
    return step_id.split("/", 1)[0]


def split_to_confirm(faults: Sequence[FaultTask]) -> list[list[FaultTask]]:
    # 2+ faults from one message are confirmed first; an urgent one skips it for all (D39).
    batches: dict[str, list[FaultTask]] = {}
    for fault in faults:
        if fault.state is TaskState.QUEUED:
            batches.setdefault(batch_of(fault.step_id), []).append(fault)
    return [
        group
        for group in batches.values()
        if len(group) >= 2 and all(fault.urgency is not Urgency.URGENT for fault in group)
    ]


def next_actionable(faults: Sequence[FaultTask]) -> FaultTask | None:
    return next((fault for fault in faults if fault.state in ACTIONABLE), None)


class Confirmation(StrEnum):
    SPLIT = "split"
    SAME = "same"


_AFTER_ANSWER = {
    (Confirmation.SPLIT, True): TaskState.SPLIT_CONFIRMED,
    # A wrong split sends the wrong staff, so a "no" goes to a person (D39).
    (Confirmation.SPLIT, False): TaskState.HELD,
    (Confirmation.SAME, True): TaskState.LINKING,
    (Confirmation.SAME, False): TaskState.DRAFTING,
}


def answered(
    faults: Sequence[FaultTask], confirmation: Confirmation, subject: str
) -> list[FaultTask]:
    if confirmation is Confirmation.SPLIT:
        return [
            fault
            for fault in faults
            if fault.state is TaskState.AWAITING_SPLIT and batch_of(fault.step_id) == subject
        ]
    return [
        fault
        for fault in faults
        if fault.state is TaskState.AWAITING_SAME and fault.step_id == subject
    ]


def after_answer(confirmation: Confirmation, yes: bool) -> TaskState:
    return _AFTER_ANSWER[(confirmation, yes)]

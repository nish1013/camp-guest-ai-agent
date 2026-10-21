from collections.abc import Sequence

from camp_agent.domain.cases import StateReason
from camp_agent.domain.routing import (
    Category,
    Scope,
    ScopeSource,
    TaskKind,
    TaskState,
    specialist_for,
)
from camp_agent.stay.port import Booking

_HELD_REASON = {
    TaskKind.EMERGENCY: StateReason.EMERGENCY,
    TaskKind.MONEY: StateReason.MONEY,
    TaskKind.FAULT: StateReason.FAULT_REVIEW,
    TaskKind.TABLE: StateReason.BOOKING_REVIEW,
    TaskKind.QUESTION: StateReason.LLM_FAILED,
}


def approved_state(kind: TaskKind, reported: bool) -> TaskState:
    # An approved task goes back into its lane; one with no lane is done by staff.
    if kind is TaskKind.FAULT:
        # A fault never reported is checked against its cabin first (I4).
        return TaskState.DRAFTING if reported else TaskState.SPLIT_CONFIRMED
    if kind is TaskKind.TABLE:
        return TaskState.QUEUED
    return TaskState.DONE


def edit_errors(kind: TaskKind, category: Category | None, edited: bool) -> list[str]:
    # Staff edit the proposed action only, never write to the guest (D31).
    if not edited:
        return []
    if kind is not TaskKind.FAULT:
        return ["only a fault's category and urgency can be edited"]
    if category is not None and specialist_for(category) is None:
        return [f"no specialist for {category}"]
    return []


def restored_hold(held: Sequence[TaskKind]) -> StateReason | None:
    # A park keeps no hold reason (I10), so a restore takes it from the first held task.
    return _HELD_REASON[held[0]] if held else None


def staff_scope(booking: Booking) -> Scope:
    # Staff confirmed the booking by phone, so it sets the scope (D33, I7).
    return Scope(booking.cabin, booking.stay_from, booking.stay_to, ScopeSource.STAFF)

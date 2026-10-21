from datetime import date, time
from enum import StrEnum

from camp_agent.domain.cases import CaseState, CaseStatus, StateReason
from camp_agent.domain.faults import FaultType, TicketStatus
from camp_agent.domain.routing import TaskState, Team


class QuickPick(StrEnum):
    MAINTENANCE = "maintenance"
    CLEANING = "cleaning"
    RESTAURANT = "restaurant"
    QUESTION = "question"
    RECEPTION = "reception"

    @property
    def label(self) -> str:
        return self.value.capitalize()


RECEIVED = "Received"
CLARIFY = "Could you tell us a bit more about what you need?"
WAITING_ON_RECEPTION = "Waiting on reception"
WITH_RECEPTION = "With reception"
BOOKING_FOUND = "Thanks, we found your booking."
NO_BOOKING_MATCH = "We could not find a booking with those details."
BOOKINGS_DOWN = "We cannot check bookings right now."
NOT_VERIFIED = "We could not confirm your booking."
WAITING_FOR_RESTAURANT = "Waiting for the restaurant to confirm"
RESTAURANT_DECLINED = "The restaurant could not take this booking."
CLOSED = "Closed"
RECEPTION_OPENS = "Reception opens at {:%H:%M}."
LOGGED = {
    Team.MAINTENANCE: "Logged with maintenance",
    Team.HOUSEKEEPING: "Logged with housekeeping",
}
WORKING = {
    Team.MAINTENANCE: "Maintenance is working on it",
    Team.HOUSEKEEPING: "Housekeeping is working on it",
}
TICKET_DONE = "Done"
TICKET_CANCELLED = "Cancelled"

_HELD: dict[StateReason | None, str] = {
    StateReason.MONEY: WAITING_ON_RECEPTION,
    StateReason.CLARIFY_LIMIT: WAITING_ON_RECEPTION,
    StateReason.LLM_FAILED: WITH_RECEPTION,
    StateReason.FAULT_REVIEW: WAITING_ON_RECEPTION,
    StateReason.TICKETING_DOWN: WITH_RECEPTION,
    StateReason.BOOKING_REVIEW: WAITING_ON_RECEPTION,
}


def guest_status(
    status: CaseStatus,
    emergency_guidance: str,
    reception: str,
    reception_opens: time | None = None,
) -> str:
    # reception_opens is set while the desk is closed: a held case waits for it (D30).
    if status.state is CaseState.HELD:
        if status.reason is StateReason.EMERGENCY:
            return emergency_guidance
        if reception_opens is not None:
            return RECEPTION_OPENS.format(reception_opens)
        return _HELD.get(status.reason, WAITING_ON_RECEPTION)
    if status.state is CaseState.PARKED and status.reason is StateReason.VERIFICATION:
        return f"{NOT_VERIFIED} {reception}"
    if status.state is CaseState.CLOSED:
        return CLOSED
    if status.state is CaseState.OPEN and status.clarify_rounds > 0:
        return CLARIFY
    return RECEIVED


def split_question(summaries: list[str]) -> str:
    return f"I found {len(summaries)} issues: {', '.join(summaries)}. Correct?"


def same_question(fault_type: FaultType, at: str) -> str:
    return f"Same problem as the {at} {fault_type.replace('_', ' ')} report?"


def table_line(party: int, day: date, at: time) -> str:
    return f"Table for {party} at {at:%H:%M} on {day.day} {day:%b}"


def ticket_status(team: Team, status: TicketStatus | None) -> str:
    # The line follows the ticket system's status, so a job reads done only when it is (D25).
    if status is TicketStatus.IN_PROGRESS:
        return WORKING[team]
    if status is TicketStatus.DONE:
        return TICKET_DONE
    if status is TicketStatus.CANCELLED:
        return TICKET_CANCELLED
    return LOGGED[team]


def booking_status(state: TaskState, party: int, at: time) -> str:
    # "Booked" only after a staff confirm (D12).
    if state is TaskState.BOOKING_CONFIRMED:
        return f"Booked: table for {party} at {at:%H:%M}."
    if state is TaskState.BOOKING_DECLINED:
        return RESTAURANT_DECLINED
    return WAITING_FOR_RESTAURANT

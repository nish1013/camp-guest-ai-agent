from camp_agent.domain.case_state import CaseState, StateReason
from camp_agent.domain.case_status import CaseStatus
from camp_agent.domain.fault_type import FaultType
from camp_agent.domain.specialist import Team

RECEIVED = "Received"
CLARIFY = "Could you tell us a bit more about what you need?"
WAITING_ON_RECEPTION = "Waiting on reception"
WITH_RECEPTION = "With reception"
BOOKING_FOUND = "Thanks, we found your booking."
NO_BOOKING_MATCH = "We could not find a booking with those details."
BOOKINGS_DOWN = "We cannot check bookings right now."
NOT_VERIFIED = "We could not confirm your booking."
LOGGED = {
    Team.MAINTENANCE: "Logged with maintenance",
    Team.HOUSEKEEPING: "Logged with housekeeping",
}

_HELD: dict[StateReason | None, str] = {
    StateReason.MONEY: WAITING_ON_RECEPTION,
    StateReason.CLARIFY_LIMIT: WAITING_ON_RECEPTION,
    StateReason.LLM_FAILED: WITH_RECEPTION,
    StateReason.FAULT_REVIEW: WAITING_ON_RECEPTION,
    StateReason.TICKETING_DOWN: WITH_RECEPTION,
}


def guest_status(status: CaseStatus, emergency_guidance: str, reception: str) -> str:
    if status.state is CaseState.HELD:
        if status.reason is StateReason.EMERGENCY:
            return emergency_guidance
        return _HELD.get(status.reason, WAITING_ON_RECEPTION)
    if status.state is CaseState.PARKED and status.reason is StateReason.VERIFICATION:
        return f"{NOT_VERIFIED} {reception}"
    if status.state is CaseState.OPEN and status.clarify_rounds > 0:
        return CLARIFY
    return RECEIVED


def split_question(summaries: list[str]) -> str:
    return f"I found {len(summaries)} issues: {', '.join(summaries)}. Correct?"


def same_question(fault_type: FaultType, at: str) -> str:
    return f"Same problem as the {at} {fault_type.replace('_', ' ')} report?"

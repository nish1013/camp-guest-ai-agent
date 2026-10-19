from camp_agent.domain.case_state import CaseState, StateReason
from camp_agent.domain.case_status import CaseStatus

RECEIVED = "Received"
CLARIFY = "Could you tell us a bit more about what you need?"
WAITING_ON_RECEPTION = "Waiting on reception"
WITH_RECEPTION = "With reception"

_HELD: dict[StateReason | None, str] = {
    StateReason.MONEY: WAITING_ON_RECEPTION,
    StateReason.CLARIFY_LIMIT: WAITING_ON_RECEPTION,
    StateReason.LLM_FAILED: WITH_RECEPTION,
}


def guest_status(status: CaseStatus, emergency_guidance: str) -> str:
    if status.state is CaseState.HELD:
        if status.reason is StateReason.EMERGENCY:
            return emergency_guidance
        return _HELD.get(status.reason, WAITING_ON_RECEPTION)
    if status.state is CaseState.OPEN and status.clarify_rounds > 0:
        return CLARIFY
    return RECEIVED

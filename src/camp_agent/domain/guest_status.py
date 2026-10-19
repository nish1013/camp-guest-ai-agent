from camp_agent.domain.case_state import CaseState

_TEMPLATES: dict[CaseState, str] = {
    CaseState.OPEN: "Received",
}


def guest_status(state: CaseState) -> str:
    return _TEMPLATES[state]

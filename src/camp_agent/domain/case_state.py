from enum import StrEnum


class CaseState(StrEnum):
    OPEN = "open"
    HELD = "held"
    PARKED = "parked"


class StateReason(StrEnum):
    EMERGENCY = "emergency"
    MONEY = "money"
    LLM_FAILED = "llm_failed"
    CLARIFY_LIMIT = "clarify_limit"
    SPAM = "spam"
    VERIFICATION = "verification"


LIVE_STATES = frozenset({CaseState.OPEN, CaseState.HELD, CaseState.PARKED})

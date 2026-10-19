from typing import TypedDict

from camp_agent.domain.cabin_reports import SavedReport
from camp_agent.llm.llm_types import Classification

SAFETY = "safety"
VERIFY = "verify"
PARK = "park"
CLARIFY = "clarify"
SPLIT = "split"
CLASSIFY = "classify"
ROUTE_GUARD = "route_guard"
ANSWER = "answer"
LLM_FAILED = "llm_failed"
CONFIRM_SPLIT = "confirm_split"
REPORT = "report"
SAME = "same"
SPECIALIST = "specialist"
LINK = "link"
BOOKING = "booking"
DISPATCH = "dispatch"


class TriageState(TypedDict):
    case_id: int
    batch_key: str
    text: str
    intents: list[str]
    index: int
    classification: Classification | None
    failed_step: str
    next: str
    fault: str
    table: str
    drafts: int
    rejected_for: list[str]
    report: SavedReport | None


class TriageUpdate(TypedDict, total=False):
    intents: list[str]
    index: int
    classification: Classification | None
    failed_step: str
    next: str
    fault: str
    table: str
    drafts: int
    rejected_for: list[str]
    report: SavedReport | None


def start_state(case_id: int, batch_key: str, text: str, entry: str) -> TriageState:
    return {
        "case_id": case_id,
        "batch_key": batch_key,
        "text": text,
        "intents": [],
        "index": 0,
        "classification": None,
        "failed_step": "",
        "next": entry,
        "fault": "",
        "table": "",
        "drafts": 0,
        "rejected_for": [],
        "report": None,
    }

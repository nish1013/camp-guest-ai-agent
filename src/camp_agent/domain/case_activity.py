from collections.abc import Collection

from camp_agent.domain.case_state import CaseState
from camp_agent.domain.case_status import CaseStatus
from camp_agent.domain.route_guard import TaskState

_ACTED = frozenset({TaskState.TICKETED})
_ASKING = frozenset({TaskState.AWAITING_SCOPE, TaskState.AWAITING_SPLIT, TaskState.AWAITING_SAME})


def in_action(task_states: Collection[TaskState]) -> bool:
    return not _ACTED.isdisjoint(task_states)


def asks_guest(status: CaseStatus, task_states: Collection[TaskState]) -> bool:
    clarifying = status.state is CaseState.OPEN and status.clarify_rounds > 0
    return clarifying or not _ASKING.isdisjoint(task_states)


def triages_follow_up(status: CaseStatus, task_states: Collection[TaskState]) -> bool:
    # A case in action takes new messages for staff to read; only an open question is triaged.
    return not in_action(task_states) or asks_guest(status, task_states)

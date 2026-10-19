from datetime import datetime

from camp_agent.domain.route_guard import TaskState
from camp_agent.domain.scope import Scope
from camp_agent.graph.triage_store import TriageStore
from camp_agent.graph.triage_types import CaseSnapshot, StepRecord, TaskHold, TaskTransition


async def hold_task(
    store: TriageStore,
    case_id: int,
    hold: TaskHold,
    now: datetime,
    case: CaseSnapshot | None = None,
) -> None:
    # The task leaves the actionable states, so no later run retries it on its own.
    case = case or await store.load(case_id)
    status = case.status.hold(hold.reason, now)
    move = TaskTransition(hold.step_id, TaskState.HELD, hold.expected)
    step = StepRecord(hold.audit, case.change(status), transitions=(move,), validation=hold.record)
    await store.commit(case_id, step)


def required_scope(case: CaseSnapshot) -> Scope:
    # A fault or a table reaches its desk only once the route guard saw a scope (D19).
    if case.scope is None:
        raise RuntimeError("a task without a scope reached its desk")
    return case.scope

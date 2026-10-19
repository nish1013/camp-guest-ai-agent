import pytest

from camp_agent.domain.route_guard import Category, Route, TaskKind, TaskState, guard_route

HELD = frozenset({"refund", "compensation", "cabin_move", "safety_close_out"})


@pytest.mark.parametrize(
    "category, route, has_scope, kind, state",
    [
        (Category.REFUND, Route.FAULT, True, TaskKind.MONEY, TaskState.HELD),
        (Category.SAFETY_CLOSE_OUT, Route.QUESTION, True, TaskKind.MONEY, TaskState.HELD),
        (Category.OTHER, Route.MONEY, True, TaskKind.MONEY, TaskState.HELD),
        (Category.MAINTENANCE, Route.FAULT, True, TaskKind.FAULT, TaskState.QUEUED),
        (Category.MAINTENANCE, Route.FAULT, False, TaskKind.FAULT, TaskState.AWAITING_SCOPE),
        (Category.RESTAURANT, Route.TABLE, False, TaskKind.TABLE, TaskState.AWAITING_SCOPE),
        (Category.INFORMATION, Route.QUESTION, False, TaskKind.QUESTION, TaskState.QUEUED),
    ],
    ids=[
        "refund-as-fault",
        "close-out-as-question",
        "money-route",
        "fault",
        "fault-no-scope",
        "table-no-scope",
        "question-no-scope",
    ],
)
def test_us8_route_guard(
    category: Category, route: Route, has_scope: bool, kind: TaskKind, state: TaskState
) -> None:
    decision = guard_route(category, route, has_scope, HELD)

    assert (decision.kind, decision.state) == (kind, state)

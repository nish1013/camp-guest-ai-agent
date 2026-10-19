from datetime import date

import pytest

from camp_agent.domain.route_guard import Category, Route, TaskKind, TaskState, guard_route
from camp_agent.domain.scope import Scope, ScopeSource

HELD = frozenset({"refund", "compensation", "cabin_move", "safety_close_out"})
C12 = Scope("C12", date(2026, 10, 18), date(2026, 10, 25), ScopeSource.QR)
OCT_19 = date(2026, 10, 19)


@pytest.mark.parametrize(
    "category, route, scope, kind, state",
    [
        (Category.REFUND, Route.FAULT, C12, TaskKind.MONEY, TaskState.HELD),
        (Category.SAFETY_CLOSE_OUT, Route.QUESTION, C12, TaskKind.MONEY, TaskState.HELD),
        (Category.OTHER, Route.MONEY, C12, TaskKind.MONEY, TaskState.HELD),
        (Category.MAINTENANCE, Route.FAULT, C12, TaskKind.FAULT, TaskState.QUEUED),
        (Category.MAINTENANCE, Route.FAULT, None, TaskKind.FAULT, TaskState.AWAITING_SCOPE),
        (Category.RESTAURANT, Route.TABLE, C12, TaskKind.TABLE, TaskState.QUEUED),
        (Category.RESTAURANT, Route.TABLE, None, TaskKind.TABLE, TaskState.AWAITING_SCOPE),
        (Category.INFORMATION, Route.QUESTION, None, TaskKind.QUESTION, TaskState.QUEUED),
    ],
    ids=[
        "refund-as-fault",
        "close-out-as-question",
        "money-route",
        "fault",
        "fault-no-scope",
        "table",
        "table-no-scope",
        "question-no-scope",
    ],
)
def test_us8_route_guard(
    category: Category, route: Route, scope: Scope | None, kind: TaskKind, state: TaskState
) -> None:
    decision = guard_route(category, route, scope, OCT_19, HELD)

    assert (decision.kind, decision.state) == (kind, state)


@pytest.mark.parametrize(
    "route, today, kind",
    [
        (Route.TABLE, date(2026, 10, 17), TaskKind.QUESTION),
        (Route.TABLE, date(2026, 10, 18), TaskKind.TABLE),
        (Route.TABLE, date(2026, 10, 25), TaskKind.TABLE),
        (Route.TABLE, date(2026, 10, 26), TaskKind.QUESTION),
        (Route.FAULT, date(2026, 10, 26), TaskKind.QUESTION),
    ],
    ids=["before-arrival", "arrival-day", "last-day", "after-check-out", "fault-after-check-out"],
)
def test_d19_request_needs_active_stay(route: Route, today: date, kind: TaskKind) -> None:
    decision = guard_route(Category.RESTAURANT, route, C12, today, HELD)

    assert (decision.kind, decision.state) == (kind, TaskState.QUEUED)

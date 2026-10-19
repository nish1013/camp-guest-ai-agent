from collections.abc import Set
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from camp_agent.domain.scope import Scope


class Category(StrEnum):
    MAINTENANCE = "maintenance"
    HOUSEKEEPING = "housekeeping"
    RESTAURANT = "restaurant"
    INFORMATION = "information"
    REFUND = "refund"
    COMPENSATION = "compensation"
    CABIN_MOVE = "cabin_move"
    SAFETY_CLOSE_OUT = "safety_close_out"
    OTHER = "other"


class Route(StrEnum):
    QUESTION = "question"
    FAULT = "fault"
    TABLE = "table"
    MONEY = "money"


class TaskKind(StrEnum):
    QUESTION = "question"
    FAULT = "fault"
    TABLE = "table"
    MONEY = "money"
    EMERGENCY = "emergency"


class TaskState(StrEnum):
    QUEUED = "queued"
    AWAITING_SCOPE = "awaiting_scope"
    HELD = "held"
    DONE = "done"
    AWAITING_SPLIT = "awaiting_split"
    SPLIT_CONFIRMED = "split_confirmed"
    AWAITING_SAME = "awaiting_same"
    DRAFTING = "drafting"
    LINKING = "linking"
    TICKETED = "ticketed"
    BOOKING_REQUESTED = "booking_requested"


@dataclass(frozen=True)
class RouteDecision:
    kind: TaskKind
    state: TaskState


_NEEDS_SCOPE = frozenset({TaskKind.FAULT, TaskKind.TABLE})


def guard_route(
    category: Category,
    route: Route,
    scope: Scope | None,
    today: date,
    held_categories: Set[str],
) -> RouteDecision:
    # The category is checked as well as the route: a refund proposed as a fault is held (D36).
    if category in held_categories or route is Route.MONEY:
        return RouteDecision(TaskKind.MONEY, TaskState.HELD)
    kind = TaskKind(route.value)
    if kind in _NEEDS_SCOPE:
        if scope is None:
            return RouteDecision(kind, TaskState.AWAITING_SCOPE)
        # Before arrival or after check-out a request gets a guide answer only (D19).
        if not scope.active_on(today):
            return RouteDecision(TaskKind.QUESTION, TaskState.QUEUED)
    return RouteDecision(kind, TaskState.QUEUED)

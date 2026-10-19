from collections.abc import Set
from dataclasses import dataclass
from enum import StrEnum


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


@dataclass(frozen=True)
class RouteDecision:
    kind: TaskKind
    state: TaskState


_NEEDS_SCOPE = frozenset({TaskKind.FAULT, TaskKind.TABLE})


def guard_route(
    category: Category, route: Route, has_scope: bool, held_categories: Set[str]
) -> RouteDecision:
    # The category is checked as well as the route: a refund proposed as a fault is held (D36).
    if category in held_categories or route is Route.MONEY:
        return RouteDecision(TaskKind.MONEY, TaskState.HELD)
    kind = TaskKind(route.value)
    if kind in _NEEDS_SCOPE and not has_scope:
        return RouteDecision(kind, TaskState.AWAITING_SCOPE)
    return RouteDecision(kind, TaskState.QUEUED)

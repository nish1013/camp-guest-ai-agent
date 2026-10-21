from collections.abc import Set
from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class ScopeSource(StrEnum):
    QR = "qr"
    STEP_UP = "step_up"
    STAFF = "staff"


@dataclass(frozen=True)
class Scope:
    cabin: str
    stay_from: date
    stay_to: date
    source: ScopeSource

    def active_on(self, today: date) -> bool:
        return self.stay_from <= today <= self.stay_to


class Urgency(StrEnum):
    URGENT = "urgent"
    NORMAL = "normal"
    CAN_WAIT = "can_wait"


_RANK = {Urgency.CAN_WAIT: 0, Urgency.NORMAL: 1, Urgency.URGENT: 2}


def higher_urgency(a: Urgency, b: Urgency) -> Urgency:
    return a if _RANK[a] >= _RANK[b] else b


def urgency_rank(urgency: Urgency) -> int:
    return _RANK[urgency]


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
    BOOKING_CONFIRMED = "booking_confirmed"
    BOOKING_DECLINED = "booking_declined"
    REJECTED = "rejected"


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


class Team(StrEnum):
    MAINTENANCE = "maintenance"
    HOUSEKEEPING = "housekeeping"


_TEAMS = {Category.MAINTENANCE: Team.MAINTENANCE, Category.HOUSEKEEPING: Team.HOUSEKEEPING}


def specialist_for(category: Category) -> Team | None:
    return _TEAMS.get(category)

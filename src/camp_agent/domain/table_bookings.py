from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, time

from camp_agent.domain.routing import TaskState

TO_BOOK = frozenset({TaskState.QUEUED})
REQUESTED = frozenset(
    {TaskState.BOOKING_REQUESTED, TaskState.BOOKING_CONFIRMED, TaskState.BOOKING_DECLINED}
)


@dataclass(frozen=True)
class TableBooking:
    cabin: str
    party: int
    day: date
    at: time


@dataclass(frozen=True)
class BookingRequest:
    state: TaskState
    booking: TableBooking


@dataclass(frozen=True)
class TableTask:
    step_id: str
    state: TaskState
    summary: str


def next_to_book(tables: Sequence[TableTask]) -> TableTask | None:
    return next((table for table in tables if table.state in TO_BOOK), None)

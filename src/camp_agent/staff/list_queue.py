from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncEngine

from camp_agent.clock import Clock
from camp_agent.db.case_record import CaseRecord
from camp_agent.db.case_repository import CaseRepository
from camp_agent.domain.case_state import CaseState
from camp_agent.domain.desk_hours import DeskHours, is_overdue
from camp_agent.domain.queue_order import queue_rank
from camp_agent.staff.staff_types import QueueItem

_QUEUED = (CaseState.OPEN, CaseState.HELD)


class ListQueue:
    def __init__(self, engine: AsyncEngine, clock: Clock, desk: DeskHours, gate: timedelta) -> None:
        self._engine = engine
        self._clock = clock
        self._desk = desk
        self._gate = gate

    async def __call__(self) -> list[QueueItem]:
        async with self._engine.connect() as conn:
            found = await CaseRepository(conn).in_states(_QUEUED)
        now = self._clock.now()
        items = [
            QueueItem(case, is_overdue(case.status.held_at, now, self._desk, self._gate))
            for case in found
        ]
        return sorted(items, key=_rank)

    async def parked(self) -> list[CaseRecord]:
        async with self._engine.connect() as conn:
            return await CaseRepository(conn).in_states((CaseState.PARKED,))


def _rank(item: QueueItem) -> tuple[int, bool, datetime]:
    return queue_rank(item.case.status.urgency, item.overdue, item.case.created_at)

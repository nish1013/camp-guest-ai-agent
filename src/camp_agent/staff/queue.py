from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncEngine

from camp_agent.clock import Clock
from camp_agent.db.audit import AuditRepository, StaffAuditLine
from camp_agent.db.cases import CaseRecord, CaseRepository
from camp_agent.db.messages import MessageRepository, StaffMessage
from camp_agent.db.tasks import StaffTask, TaskRepository
from camp_agent.domain.cases import CaseState, DeskHours, is_overdue, queue_rank


@dataclass(frozen=True)
class QueueItem:
    case: CaseRecord
    overdue: bool


@dataclass(frozen=True)
class CaseDetail:
    case: CaseRecord
    overdue: bool
    tasks: list[StaffTask]
    messages: list[StaffMessage]
    audit: list[StaffAuditLine]


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


class ShowCase:
    def __init__(self, engine: AsyncEngine, clock: Clock, desk: DeskHours, gate: timedelta) -> None:
        self._engine = engine
        self._clock = clock
        self._desk = desk
        self._gate = gate

    # Messages are shown in full: a follow-up that joined a case in action is read only here.
    async def __call__(self, case_id: int) -> CaseDetail | None:
        async with self._engine.connect() as conn:
            case = await CaseRepository(conn).find(case_id)
            if case is None:
                return None
            tasks = await TaskRepository(conn).for_staff(case_id)
            messages = await MessageRepository(conn).for_staff(case_id)
            audit = await AuditRepository(conn).for_case(case_id)
        overdue = is_overdue(case.status.held_at, self._clock.now(), self._desk, self._gate)
        return CaseDetail(case, overdue, tasks, messages, audit)

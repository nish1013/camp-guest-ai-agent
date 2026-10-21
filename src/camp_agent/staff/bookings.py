from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine

from camp_agent.clock import Clock
from camp_agent.db.tasks import TaskRepository
from camp_agent.domain.cases import AuditEntry, settled
from camp_agent.domain.routing import TaskState
from camp_agent.graph.triage import TaskTransition
from camp_agent.notification.port import CaseWatch
from camp_agent.staff.case_lock import StaffCaseLock, StaffConflictError


@dataclass(frozen=True)
class BookingDecision:
    task_id: int
    version: int
    confirm: bool


BOOKING_STATUS = "booking_status"


class SetBookingStatus:
    def __init__(self, engine: AsyncEngine, clock: Clock, watch: CaseWatch | None = None) -> None:
        self._engine = engine
        self._lock = StaffCaseLock(engine, clock, watch)
        self._clock = clock

    # Only staff turn a request into a booking (D12). Returns the case id, or None.
    async def __call__(self, decision: BookingDecision) -> int | None:
        async with self._engine.connect() as conn:
            task = await TaskRepository(conn).find_by_id(decision.task_id)
        if task is None:
            return None
        target = TaskState.BOOKING_CONFIRMED if decision.confirm else TaskState.BOOKING_DECLINED
        async with self._lock(task.case_id, decision.version) as staff:
            if staff is None:
                return None
            move = TaskTransition(task.step_id, target, TaskState.BOOKING_REQUESTED)
            # A second confirm or a decline after a confirm finds the request already answered.
            if not await TaskRepository(staff.conn).transition(task.case_id, move):
                raise StaffConflictError(task.case_id)
            status = settled(staff.case.status, await staff.progress(), self._clock.now())
            detail = {"step_id": task.step_id, "case": status.state}
            await staff.save(status, AuditEntry(BOOKING_STATUS, target, detail))
        return task.case_id

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncEngine

from camp_agent.clock import Clock
from camp_agent.db.audit_repository import AuditRepository
from camp_agent.db.case_repository import CaseRepository
from camp_agent.db.message_repository import MessageRepository
from camp_agent.db.task_repository import TaskRepository
from camp_agent.domain.desk_hours import DeskHours, is_overdue
from camp_agent.staff.staff_types import CaseDetail


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

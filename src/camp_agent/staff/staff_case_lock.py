from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from camp_agent.clock import Clock
from camp_agent.db.audit_repository import AuditRepository
from camp_agent.db.case_record import CaseRecord
from camp_agent.db.case_repository import CaseRepository
from camp_agent.db.task_repository import TaskRepository
from camp_agent.domain.audit_entry import AuditEntry
from camp_agent.domain.case_closure import TaskProgress
from camp_agent.domain.case_status import CaseStatus
from camp_agent.domain.run_lease import run_active
from camp_agent.domain.scope import Scope
from camp_agent.notification.case_watch import CaseWatch
from camp_agent.staff.staff_conflict_error import StaffConflictError


@dataclass(frozen=True)
class StaffCase:
    conn: AsyncConnection
    case: CaseRecord

    async def progress(self) -> list[TaskProgress]:
        return await TaskRepository(self.conn).progress(self.case.id)

    async def save(self, status: CaseStatus, audit: AuditEntry, scope: Scope | None = None) -> None:
        cases = CaseRepository(self.conn)
        version = self.case.version
        if scope is not None:
            if not await cases.set_scope(self.case.id, scope, version):
                raise StaffConflictError(self.case.id)
            version += 1
        if not await cases.save_status(self.case.id, status, version):
            raise StaffConflictError(self.case.id)
        await AuditRepository(self.conn).insert(self.case.id, audit)


class StaffCaseLock:
    def __init__(self, engine: AsyncEngine, clock: Clock, watch: CaseWatch | None) -> None:
        self._engine = engine
        self._clock = clock
        self._watch = watch

    # The row lock orders this write against the run's lease claim and every status write.
    # A form older than the case, or a run holding the lease, is a conflict (I8, I10, I11).
    @asynccontextmanager
    async def __call__(self, case_id: int, version: int) -> AsyncIterator[StaffCase | None]:
        async with self._engine.begin() as conn:
            case = await CaseRepository(conn).try_lock(case_id)
            if case is None:
                yield None
                return
            if case.version != version or run_active(case.run_lease_until, self._clock.now()):
                raise StaffConflictError(case_id)
            yield StaffCase(conn, case)
        if self._watch is not None:
            await self._watch.changed(case_id)

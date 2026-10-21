from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from camp_agent.clock import Clock
from camp_agent.db.audit import AuditRepository
from camp_agent.db.cases import CaseRecord, CaseRepository
from camp_agent.db.tasks import TaskRepository
from camp_agent.domain.cases import AuditEntry, CaseStatus, TaskProgress, run_active
from camp_agent.domain.routing import Scope
from camp_agent.notification.port import CaseWatch


class StaffConflictError(Exception):
    pass


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

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from camp_agent.db.audit import AuditRepository, ValidationRepository
from camp_agent.db.cases import CaseRepository
from camp_agent.db.reports import ReportRepository
from camp_agent.db.tasks import TaskRepository
from camp_agent.db.tickets import lock_ticket_xact
from camp_agent.domain.cases import AuditEntry, CaseState, settled
from camp_agent.domain.faults import FaultTask, ReportDraft, SavedReport
from camp_agent.domain.routing import TaskState
from camp_agent.domain.table_bookings import TableTask
from camp_agent.graph.triage import (
    CaseSnapshot,
    LinkTarget,
    StaleCaseError,
    StepRecord,
    WaitingTask,
)
from camp_agent.notification.port import CaseWatch


class PgLockedCase:
    def __init__(self, conn: AsyncConnection, case_id: int, case: CaseSnapshot) -> None:
        self._conn = conn
        self._case_id = case_id
        self.case = case

    async def commit(self, step: StepRecord) -> None:
        await write_step(self._conn, self._case_id, step)


async def write_step(conn: AsyncConnection, case_id: int, step: StepRecord) -> None:
    # Taken before the case row, as the status handler does, so the two never wait in a circle.
    for transition in step.transitions:
        if transition.ticket is not None:
            await lock_ticket_xact(conn, transition.ticket.ref)
    change = step.status
    if change is not None and not await CaseRepository(conn).save_status(
        case_id, change.status, change.version
    ):
        raise StaleCaseError(case_id)
    await AuditRepository(conn).insert(case_id, step.audit)
    task_repository = TaskRepository(conn)
    await task_repository.insert(case_id, step.tasks)
    # A transition can make a task a question, which only then may hold an answer.
    for transition in step.transitions:
        await task_repository.transition(case_id, transition)
    await task_repository.save_answers(case_id, step.answers)
    if step.validation is not None:
        await ValidationRepository(conn).insert(case_id, step.validation)


CLOSED = AuditEntry("case", "closed")


class PgTriageStore:
    def __init__(self, engine: AsyncEngine, watch: CaseWatch | None = None) -> None:
        self._engine = engine
        self._watch = watch

    async def load(self, case_id: int) -> CaseSnapshot:
        async with self._engine.connect() as conn:
            case = await CaseRepository(conn).get(case_id)
        return CaseSnapshot(case.status, case.scope, case.version)

    async def awaiting_scope(self, case_id: int) -> list[WaitingTask]:
        async with self._engine.connect() as conn:
            return await TaskRepository(conn).awaiting_scope(case_id)

    async def faults(self, case_id: int) -> list[FaultTask]:
        async with self._engine.connect() as conn:
            return await TaskRepository(conn).faults(case_id)

    async def tables(self, case_id: int) -> list[TableTask]:
        async with self._engine.connect() as conn:
            return await TaskRepository(conn).tables(case_id)

    async def task_states(self, case_id: int) -> list[TaskState]:
        async with self._engine.connect() as conn:
            return await TaskRepository(conn).states(case_id)

    async def save_report(self, case_id: int, draft: ReportDraft) -> SavedReport:
        async with self._engine.begin() as conn:
            return await ReportRepository(conn).save(case_id, draft)

    async def link_target(self, report_id: int) -> LinkTarget | None:
        async with self._engine.connect() as conn:
            return await ReportRepository(conn).link_target(report_id)

    @asynccontextmanager
    async def lock_case(self, case_id: int) -> AsyncIterator[PgLockedCase]:
        async with self._engine.begin() as conn:
            case = await CaseRepository(conn).lock(case_id)
            yield PgLockedCase(conn, case_id, CaseSnapshot(case.status, case.scope, case.version))
        await self._changed(case_id)

    async def close_if_done(self, case_id: int, now: datetime) -> None:
        if await self._close_if_done(case_id, now):
            await self._changed(case_id)

    async def commit(self, case_id: int, step: StepRecord) -> None:
        async with self._engine.begin() as conn:
            await write_step(conn, case_id, step)
        await self._changed(case_id)

    async def _close_if_done(self, case_id: int, now: datetime) -> bool:
        async with self._engine.begin() as conn:
            cases = CaseRepository(conn)
            case = await cases.lock(case_id)
            status = settled(case.status, await TaskRepository(conn).progress(case_id), now)
            if status.state is not CaseState.CLOSED or case.status.state is CaseState.CLOSED:
                return False
            if not await cases.save_status(case_id, status, case.version):
                raise RuntimeError("a locked case changed")
            await AuditRepository(conn).insert(case_id, CLOSED)
        return True

    async def _changed(self, case_id: int) -> None:
        if self._watch is not None:
            await self._watch.changed(case_id)

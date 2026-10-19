from sqlalchemy.ext.asyncio import AsyncEngine

from camp_agent.db.audit_repository import AuditRepository
from camp_agent.db.case_repository import CaseRepository
from camp_agent.db.report_repository import ReportRepository
from camp_agent.db.task_repository import TaskRepository
from camp_agent.db.validation_repository import ValidationRepository
from camp_agent.domain.cabin_reports import ReportDraft, SavedReport
from camp_agent.domain.fault_flow import FaultTask
from camp_agent.graph.stale_case_error import StaleCaseError
from camp_agent.graph.triage_types import (
    CaseSnapshot,
    LinkTarget,
    StepRecord,
    WaitingTask,
)


class PgTriageStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

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

    async def save_report(self, case_id: int, draft: ReportDraft) -> SavedReport:
        async with self._engine.begin() as conn:
            return await ReportRepository(conn).save(case_id, draft)

    async def link_target(self, report_id: int) -> LinkTarget | None:
        async with self._engine.connect() as conn:
            return await ReportRepository(conn).link_target(report_id)

    async def commit(self, case_id: int, step: StepRecord) -> None:
        async with self._engine.begin() as conn:
            change = step.status
            if change is not None and not await CaseRepository(conn).save_status(
                case_id, change.status, change.version
            ):
                raise StaleCaseError(case_id)
            await AuditRepository(conn).insert(case_id, step.audit)
            task_repository = TaskRepository(conn)
            await task_repository.insert(case_id, step.tasks)
            await task_repository.save_answers(case_id, step.answers)
            for transition in step.transitions:
                await task_repository.transition(case_id, transition)
            if step.validation is not None:
                await ValidationRepository(conn).insert(case_id, step.validation)

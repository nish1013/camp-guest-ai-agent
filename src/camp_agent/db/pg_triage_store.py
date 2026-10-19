from sqlalchemy.ext.asyncio import AsyncEngine

from camp_agent.db.audit_repository import AuditRepository
from camp_agent.db.case_repository import CaseRepository
from camp_agent.db.task_repository import TaskRepository
from camp_agent.graph.triage_types import CaseSnapshot, StepRecord


class PgTriageStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def load(self, case_id: int) -> CaseSnapshot:
        async with self._engine.connect() as conn:
            case = await CaseRepository(conn).get(case_id)
        return CaseSnapshot(case.status, case.scope)

    async def commit(self, case_id: int, step: StepRecord) -> None:
        async with self._engine.begin() as conn:
            await AuditRepository(conn).insert(case_id, step.audit)
            if step.status is not None:
                await CaseRepository(conn).save_status(case_id, step.status)
            await TaskRepository(conn).insert(case_id, step.tasks)

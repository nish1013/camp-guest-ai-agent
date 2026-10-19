from sqlalchemy.ext.asyncio import AsyncConnection

from camp_agent.db.audit_repository import AuditRepository
from camp_agent.db.case_repository import CaseRepository
from camp_agent.db.task_repository import TaskRepository
from camp_agent.db.validation_repository import ValidationRepository
from camp_agent.graph.stale_case_error import StaleCaseError
from camp_agent.graph.triage_types import CaseSnapshot, StepRecord


class PgLockedCase:
    def __init__(self, conn: AsyncConnection, case_id: int, case: CaseSnapshot) -> None:
        self._conn = conn
        self._case_id = case_id
        self.case = case

    async def commit(self, step: StepRecord) -> None:
        await write_step(self._conn, self._case_id, step)


async def write_step(conn: AsyncConnection, case_id: int, step: StepRecord) -> None:
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

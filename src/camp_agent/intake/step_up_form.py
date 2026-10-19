from sqlalchemy.ext.asyncio import AsyncEngine

from camp_agent.db.case_record import CaseRecord
from camp_agent.db.task_repository import TaskRepository
from camp_agent.db.verification_repository import VerificationRepository
from camp_agent.domain.step_up import asks_step_up, limit_reached


class StepUpForm:
    def __init__(self, engine: AsyncEngine, failure_limit: int) -> None:
        self._engine = engine
        self._limit = failure_limit

    async def shown(self, case: CaseRecord) -> bool:
        if case.scope is not None:
            return False
        async with self._engine.connect() as conn:
            waiting = await TaskRepository(conn).has_awaiting_scope(case.id)
            failures = await VerificationRepository(conn).count_failures(case.id)
        return asks_step_up(case.status, case.scope, waiting, limit_reached(failures, self._limit))

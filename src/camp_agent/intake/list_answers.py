from sqlalchemy.ext.asyncio import AsyncEngine

from camp_agent.db.answered_question import AnsweredQuestion
from camp_agent.db.task_repository import TaskRepository


class ListAnswers:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def __call__(self, case_id: int) -> list[AnsweredQuestion]:
        async with self._engine.connect() as conn:
            return await TaskRepository(conn).answers(case_id)

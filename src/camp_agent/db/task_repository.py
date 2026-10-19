from collections.abc import Sequence

from sqlalchemy import exists, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from camp_agent.db.answered_question import AnsweredQuestion
from camp_agent.db.tables import tasks
from camp_agent.domain.route_guard import Category, TaskKind, TaskState
from camp_agent.graph.triage_types import TaskAnswer, TaskDraft, TaskTransition, WaitingTask


class TaskRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def insert(self, case_id: int, drafts: Sequence[TaskDraft]) -> None:
        if not drafts:
            return
        rows = [
            {
                "case_id": case_id,
                "step_id": draft.step_id,
                "kind": draft.kind,
                "category": draft.category,
                "urgency": draft.urgency,
                "state": draft.state,
                "summary": draft.summary,
            }
            for draft in drafts
        ]
        # A re-run of a batch that crashed part-way repeats its step ids; the task already exists.
        await self._conn.execute(
            insert(tasks).on_conflict_do_nothing(index_elements=["case_id", "step_id"]), rows
        )

    async def save_answers(self, case_id: int, answers: Sequence[TaskAnswer]) -> None:
        for answer in answers:
            await self._conn.execute(
                update(tasks)
                .where(tasks.c.case_id == case_id, tasks.c.step_id == answer.step_id)
                .values(state=TaskState.DONE, answer=answer.text, answer_section=answer.section_id)
            )

    async def answers(self, case_id: int) -> list[AnsweredQuestion]:
        query = (
            select(tasks.c.summary, tasks.c.answer, tasks.c.answer_section)
            .where(tasks.c.case_id == case_id, tasks.c.answer.is_not(None))
            .order_by(tasks.c.id)
        )
        rows = (await self._conn.execute(query)).all()
        return [AnsweredQuestion(row.summary, row.answer, row.answer_section) for row in rows]

    async def awaiting_scope(self, case_id: int) -> list[WaitingTask]:
        query = (
            select(tasks.c.step_id, tasks.c.kind, tasks.c.category)
            .where(tasks.c.case_id == case_id, tasks.c.state == TaskState.AWAITING_SCOPE)
            .order_by(tasks.c.id)
        )
        rows = (await self._conn.execute(query)).all()
        return [
            WaitingTask(row.step_id, TaskKind(row.kind), Category(row.category)) for row in rows
        ]

    async def has_awaiting_scope(self, case_id: int) -> bool:
        query = select(
            exists().where(tasks.c.case_id == case_id, tasks.c.state == TaskState.AWAITING_SCOPE)
        )
        found: bool = (await self._conn.execute(query)).scalar_one()
        return found

    async def resume(self, case_id: int, transitions: Sequence[TaskTransition]) -> None:
        for transition in transitions:
            await self._conn.execute(
                update(tasks)
                .where(
                    tasks.c.case_id == case_id,
                    tasks.c.step_id == transition.step_id,
                    tasks.c.state == TaskState.AWAITING_SCOPE,
                )
                .values(state=transition.state)
            )

from collections.abc import Sequence
from typing import Any

from sqlalchemy import and_, exists, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from camp_agent.db.answered_question import AnsweredQuestion
from camp_agent.db.tables import tasks
from camp_agent.domain.fault_flow import ACTIONABLE, FaultTask
from camp_agent.domain.fault_type import FaultType
from camp_agent.domain.route_guard import Category, TaskKind, TaskState
from camp_agent.domain.table_flow import TO_BOOK, TableBooking, TableTask
from camp_agent.domain.urgency import Urgency
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
                "fault_type": draft.fault_type,
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

    async def faults(self, case_id: int) -> list[FaultTask]:
        query = (
            select(tasks)
            .where(tasks.c.case_id == case_id, tasks.c.kind == TaskKind.FAULT)
            .order_by(tasks.c.id)
        )
        rows = (await self._conn.execute(query)).all()
        return [
            FaultTask(
                row.step_id,
                TaskState(row.state),
                Category(row.category),
                FaultType(row.fault_type),
                Urgency(row.urgency),
                row.summary,
                row.same_report_id,
            )
            for row in rows
        ]

    async def tables(self, case_id: int) -> list[TableTask]:
        query = (
            select(tasks.c.step_id, tasks.c.state, tasks.c.summary)
            .where(tasks.c.case_id == case_id, tasks.c.kind == TaskKind.TABLE)
            .order_by(tasks.c.id)
        )
        rows = (await self._conn.execute(query)).all()
        return [TableTask(row.step_id, TaskState(row.state), row.summary) for row in rows]

    async def booking_requests(self, case_id: int) -> list[TableBooking]:
        query = (
            select(tasks.c.cabin, tasks.c.booking_party, tasks.c.booking_date, tasks.c.booking_time)
            .where(tasks.c.case_id == case_id, tasks.c.state == TaskState.BOOKING_REQUESTED)
            .order_by(tasks.c.id)
        )
        rows = (await self._conn.execute(query)).all()
        return [
            TableBooking(row.cabin, row.booking_party, row.booking_date, row.booking_time)
            for row in rows
        ]

    async def states(self, case_id: int) -> list[TaskState]:
        query = select(tasks.c.state).where(tasks.c.case_id == case_id)
        return [TaskState(state) for state in (await self._conn.execute(query)).scalars()]

    async def has_actionable(self, case_id: int) -> bool:
        query = select(
            exists().where(
                tasks.c.case_id == case_id,
                or_(
                    and_(tasks.c.kind == TaskKind.FAULT, tasks.c.state.in_(ACTIONABLE)),
                    and_(tasks.c.kind == TaskKind.TABLE, tasks.c.state.in_(TO_BOOK)),
                ),
            )
        )
        found: bool = (await self._conn.execute(query)).scalar_one()
        return found

    async def transition(self, case_id: int, transition: TaskTransition) -> bool:
        values: dict[str, Any] = {"state": transition.state}
        if transition.same_report_id is not None:
            values["same_report_id"] = transition.same_report_id
        if transition.ticket is not None:
            values |= {
                "ticket_ref": transition.ticket.ref,
                "ticket_status": transition.ticket.status,
                "ticket_version": transition.ticket.version,
                "cabin": transition.ticket.cabin,
            }
        if transition.booking is not None:
            values |= {
                "cabin": transition.booking.cabin,
                "booking_party": transition.booking.party,
                "booking_date": transition.booking.day,
                "booking_time": transition.booking.at,
            }
        moved = await self._conn.execute(
            update(tasks)
            .where(
                tasks.c.case_id == case_id,
                tasks.c.step_id == transition.step_id,
                tasks.c.state == transition.expected,
            )
            .values(values)
            .returning(tasks.c.id)
        )
        return moved.one_or_none() is not None

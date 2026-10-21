from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, time
from typing import Any

from sqlalchemy import and_, exists, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from camp_agent.db.tables import reports, tasks
from camp_agent.domain.cases import TaskProgress
from camp_agent.domain.faults import ACTIONABLE, FaultTask, FaultType, TicketStatus
from camp_agent.domain.routing import Category, TaskKind, TaskState, Urgency
from camp_agent.domain.table_bookings import (
    REQUESTED,
    TO_BOOK,
    BookingRequest,
    TableBooking,
    TableTask,
)
from camp_agent.graph.triage import TaskAnswer, TaskDraft, TaskTransition, TicketLink, WaitingTask
from camp_agent.ticket.port import TicketStatusChanged


@dataclass(frozen=True)
class AnsweredQuestion:
    question: str
    answer: str
    section_id: str | None


@dataclass(frozen=True)
class TaskRef:
    case_id: int
    step_id: str


@dataclass(frozen=True)
class HeldTask:
    step_id: str
    kind: TaskKind
    reported: bool


@dataclass(frozen=True)
class Resolution:
    state: TaskState
    category: Category | None = None
    urgency: Urgency | None = None


@dataclass(frozen=True)
class StaffTask:
    id: int
    step_id: str
    kind: TaskKind
    category: Category | None
    urgency: Urgency
    state: TaskState
    summary: str
    ticket_ref: str | None
    ticket_status: TicketStatus | None
    booking_party: int | None
    booking_date: date | None
    booking_time: time | None


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
            select(tasks.c.step_id, tasks.c.kind, tasks.c.category, tasks.c.summary)
            .where(tasks.c.case_id == case_id, tasks.c.state == TaskState.AWAITING_SCOPE)
            .order_by(tasks.c.id)
        )
        rows = (await self._conn.execute(query)).all()
        return [
            WaitingTask(row.step_id, TaskKind(row.kind), Category(row.category), row.summary)
            for row in rows
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
                None if row.ticket_status is None else TicketStatus(row.ticket_status),
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

    async def booking_requests(self, case_id: int) -> list[BookingRequest]:
        query = (
            select(tasks)
            .where(tasks.c.case_id == case_id, tasks.c.state.in_(REQUESTED))
            .order_by(tasks.c.id)
        )
        rows = (await self._conn.execute(query)).all()
        return [
            BookingRequest(
                TaskState(row.state),
                TableBooking(row.cabin, row.booking_party, row.booking_date, row.booking_time),
            )
            for row in rows
        ]

    async def find_by_id(self, task_id: int) -> TaskRef | None:
        query = select(tasks.c.case_id, tasks.c.step_id).where(tasks.c.id == task_id)
        row = (await self._conn.execute(query)).one_or_none()
        return None if row is None else TaskRef(row.case_id, row.step_id)

    async def held(self, case_id: int) -> list[HeldTask]:
        reported = exists().where(
            reports.c.case_id == tasks.c.case_id, reports.c.step_id == tasks.c.step_id
        )
        query = (
            select(tasks.c.step_id, tasks.c.kind, reported.label("reported"))
            .where(tasks.c.case_id == case_id, tasks.c.state == TaskState.HELD)
            .order_by(tasks.c.id)
        )
        rows = (await self._conn.execute(query)).all()
        return [HeldTask(row.step_id, TaskKind(row.kind), row.reported) for row in rows]

    async def resolve(self, case_id: int, step_id: str, resolution: Resolution) -> bool:
        values: dict[str, Any] = {"state": resolution.state}
        if resolution.category is not None:
            values["category"] = resolution.category
        if resolution.urgency is not None:
            values["urgency"] = resolution.urgency
        moved = await self._conn.execute(
            update(tasks)
            .where(
                tasks.c.case_id == case_id,
                tasks.c.step_id == step_id,
                tasks.c.state == TaskState.HELD,
            )
            .values(values)
            .returning(tasks.c.id)
        )
        return moved.one_or_none() is not None

    async def rejected(self, case_id: int) -> list[str]:
        query = (
            select(tasks.c.summary)
            .where(tasks.c.case_id == case_id, tasks.c.state == TaskState.REJECTED)
            .order_by(tasks.c.id)
        )
        return list((await self._conn.execute(query)).scalars())

    async def for_staff(self, case_id: int) -> list[StaffTask]:
        query = select(tasks).where(tasks.c.case_id == case_id).order_by(tasks.c.id)
        return [
            StaffTask(
                row.id,
                row.step_id,
                TaskKind(row.kind),
                None if row.category is None else Category(row.category),
                Urgency(row.urgency),
                TaskState(row.state),
                row.summary,
                row.ticket_ref,
                None if row.ticket_status is None else TicketStatus(row.ticket_status),
                row.booking_party,
                row.booking_date,
                row.booking_time,
            )
            for row in (await self._conn.execute(query)).all()
        ]

    async def progress(self, case_id: int) -> list[TaskProgress]:
        query = select(tasks.c.state, tasks.c.ticket_status).where(tasks.c.case_id == case_id)
        return [
            TaskProgress(
                TaskState(row.state),
                None if row.ticket_status is None else TicketStatus(row.ticket_status),
            )
            for row in (await self._conn.execute(query)).all()
        ]

    async def cases_with_ticket(self, ticket_ref: str) -> list[int]:
        query = (
            select(tasks.c.case_id)
            .where(tasks.c.ticket_ref == ticket_ref)
            .distinct()
            .order_by(tasks.c.case_id)
        )
        return list((await self._conn.execute(query)).scalars())

    async def apply_ticket_status(self, case_id: int, event: TicketStatusChanged) -> bool:
        # A version at or below the stored one is a repeat or arrived late (D45, I12).
        applied = await self._conn.execute(
            update(tasks)
            .where(
                tasks.c.case_id == case_id,
                tasks.c.ticket_ref == event.ticket_ref,
                tasks.c.ticket_version < event.version,
            )
            .values(ticket_status=event.status, ticket_version=event.version)
            .returning(tasks.c.id)
        )
        return len(applied.all()) > 0

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
        if transition.kind is not None:
            values["kind"] = transition.kind
            if transition.kind is not TaskKind.FAULT:
                values["fault_type"] = None
        if transition.same_report_id is not None:
            values["same_report_id"] = transition.same_report_id
        if transition.ticket is not None:
            status, version = await self._freshest(transition.ticket)
            values |= {
                "ticket_ref": transition.ticket.ref,
                "ticket_status": status,
                "ticket_version": version,
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

    # Under the ticket lock: a status the handler applied to a linked task after the link read
    # it is carried over, so no event is missed (I12).
    async def _freshest(self, link: TicketLink) -> tuple[TicketStatus, int]:
        query = (
            select(tasks.c.ticket_status, tasks.c.ticket_version)
            .where(tasks.c.ticket_ref == link.ref, tasks.c.ticket_version > link.version)
            .order_by(tasks.c.ticket_version.desc())
            .limit(1)
        )
        row = (await self._conn.execute(query)).one_or_none()
        if row is None:
            return link.status, link.version
        return TicketStatus(row.ticket_status), row.ticket_version

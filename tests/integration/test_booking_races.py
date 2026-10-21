from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, time
from uuid import uuid4

import anyio
import pytest
from anyio.abc import TaskGroup
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from camp_agent.db.messages import MessageRepository
from camp_agent.db.tasks import TaskRepository
from camp_agent.db.triage_store import PgLockedCase, PgTriageStore
from camp_agent.domain.cases import AuditEntry
from camp_agent.domain.routing import Category, Route, TaskKind, TaskState, Urgency
from camp_agent.domain.table_bookings import TableBooking
from camp_agent.graph.guide_answerer import GuideAnswerer
from camp_agent.graph.langgraph_triage import LangGraphTriage
from camp_agent.graph.triage import StepRecord, TaskDraft, TaskTransition
from camp_agent.intake.runs import RunCoordinator
from camp_agent.llm.port import Classification
from camp_agent.ticket.demo_tickets import DemoTickets
from tests.fakes import FakeLlm, demo_guide, oct_19
from tests.integration.intake_support import audit, rows
from tests.integration.test_fault_races import LEASE, park, scoped_case, wait_for
from tests.unit.triage_support import POLICY, RECEPTION

pytestmark = pytest.mark.anyio

TABLE = "table for 4 at 19:30 tonight"
DINNER = Classification(category=Category.RESTAURANT, route=Route.TABLE, urgency=Urgency.NORMAL)


def booking_run(engine: AsyncEngine, store: PgTriageStore) -> RunCoordinator:
    llm = FakeLlm(classes={TABLE: DINNER})
    graph = LangGraphTriage(
        llm,
        store,
        oct_19(),
        POLICY,
        GuideAnswerer(llm, demo_guide(), RECEPTION),
        DemoTickets(engine),
    )
    return RunCoordinator(engine, graph, oct_19(), LEASE)


async def add_message(engine: AsyncEngine, case_id: int) -> None:
    async with engine.begin() as conn:
        await MessageRepository(conn).insert(uuid4(), case_id, TABLE)


def task_row(db: Engine) -> list[tuple[object, ...]]:
    return rows(db, "SELECT kind, state, booking_party FROM tasks")


async def test_i8_park_before_booking_no_request(db: Engine, async_db: AsyncEngine) -> None:
    class ParkBeforeLock(PgTriageStore):
        # Parks the case after the args passed validation and before the request is saved.
        @asynccontextmanager
        async def lock_case(self, case_id: int) -> AsyncIterator[PgLockedCase]:
            assert await park(async_db, case_id)
            async with super().lock_case(case_id) as locked:
                yield locked

    case_id = await scoped_case(async_db)
    await add_message(async_db, case_id)

    await booking_run(async_db, ParkBeforeLock(async_db)).drive(case_id)

    assert rows(db, "SELECT state, state_reason FROM cases") == [("parked", "spam")]
    assert task_row(db) == [("table", "queued", None)]
    assert audit(db)[-1] == ("booking", "stopped_parked")


async def test_i8_park_during_booking_refused(db: Engine, async_db: AsyncEngine) -> None:
    parked: list[bool] = []

    class ParkInsideLock(PgTriageStore):
        def __init__(self, engine: AsyncEngine, tg: TaskGroup) -> None:
            super().__init__(engine)
            self._tg = tg

        # A second connection parks the case while the booking request is being saved.
        @asynccontextmanager
        async def lock_case(self, case_id: int) -> AsyncIterator[PgLockedCase]:
            async with super().lock_case(case_id) as locked:

                async def attempt() -> None:
                    parked.append(await park(async_db, case_id))

                self._tg.start_soon(attempt)
                await wait_for(async_db, 1)
                yield locked

    case_id = await scoped_case(async_db)
    await add_message(async_db, case_id)

    async with anyio.create_task_group() as tg:
        await booking_run(async_db, ParkInsideLock(async_db, tg)).drive(case_id)

    assert parked == [False]
    assert rows(db, "SELECT state FROM cases") == [("open",)]
    assert task_row(db) == [("table", "booking_requested", 4)]


async def test_i5_booking_cabin_is_case_cabin(async_db: AsyncEngine) -> None:
    case_id = await scoped_case(async_db)
    draft = TaskDraft(
        "m1/t0", TaskKind.TABLE, Category.RESTAURANT, Urgency.NORMAL, TaskState.QUEUED, TABLE
    )
    async with async_db.begin() as conn:
        await TaskRepository(conn).insert(case_id, [draft])
    c14 = TableBooking("C14", 4, date(2026, 10, 19), time(19, 30))
    move = TaskTransition("m1/t0", TaskState.BOOKING_REQUESTED, TaskState.QUEUED, booking=c14)

    with pytest.raises(IntegrityError, match="fk_tasks_case_cabin"):
        await PgTriageStore(async_db).commit(
            case_id, StepRecord(AuditEntry("booking", "requested"), transitions=(move,))
        )

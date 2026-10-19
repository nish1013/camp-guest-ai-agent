from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from uuid import uuid4

import anyio
import pytest
from anyio.abc import TaskGroup
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from camp_agent.db.case_repository import CaseRepository
from camp_agent.db.message_repository import MessageRepository
from camp_agent.db.pg_locked_case import PgLockedCase
from camp_agent.db.pg_triage_store import PgTriageStore
from camp_agent.db.task_repository import TaskRepository
from camp_agent.domain.audit_entry import AuditEntry
from camp_agent.domain.cabin_reports import ReportDraft, SavedReport
from camp_agent.domain.case_state import StateReason
from camp_agent.domain.fault_type import FaultType
from camp_agent.domain.route_guard import Category, Route, TaskKind, TaskState
from camp_agent.domain.ticket_status import TicketStatus
from camp_agent.domain.urgency import Urgency
from camp_agent.graph.guide_answerer import GuideAnswerer
from camp_agent.graph.langgraph_triage import LangGraphTriage
from camp_agent.graph.triage_types import (
    StepRecord,
    TaskDraft,
    TaskTransition,
    TicketLink,
)
from camp_agent.intake.run_coordinator import RunCoordinator
from camp_agent.llm.llm_types import Classification
from camp_agent.ticket.demo_tickets import DemoTickets
from camp_agent.ticket.ticket_port import TicketPort
from camp_agent.ticket.ticket_types import TicketReceipt, TicketRequest
from tests.fakes import FakeLlm, demo_guide, oct_19
from tests.integration.intake_support import audit, count, rows
from tests.unit.triage_support import C12, POLICY, RECEPTION

pytestmark = pytest.mark.anyio

LEASE = timedelta(seconds=120)
HOT_WATER = Classification(
    category=Category.MAINTENANCE,
    route=Route.FAULT,
    urgency=Urgency.URGENT,
    fault_type=FaultType.HOT_WATER,
)
WAITING = text(
    "SELECT count(*) FROM pg_stat_activity"
    " WHERE wait_event_type = 'Lock' AND pid <> pg_backend_pid()"
)


def fault(step_id: str) -> TaskDraft:
    return TaskDraft(
        step_id,
        TaskKind.FAULT,
        Category.MAINTENANCE,
        Urgency.URGENT,
        TaskState.QUEUED,
        "no hot water",
        FaultType.HOT_WATER,
    )


async def scoped_case(engine: AsyncEngine, step_id: str | None = None) -> int:
    async with engine.begin() as conn:
        case_id = (await CaseRepository(conn).create(uuid4().hex, C12)).id
        if step_id is not None:
            await TaskRepository(conn).insert(case_id, [fault(step_id)])
    return case_id


async def wait_for(engine: AsyncEngine, waiting: int) -> None:
    with anyio.fail_after(5):
        while True:
            async with engine.connect() as conn:
                if (await conn.execute(WAITING)).scalar_one() >= waiting:
                    return
            await anyio.sleep(0.01)


def triage(
    engine: AsyncEngine, tickets: TicketPort, store: PgTriageStore | None = None
) -> RunCoordinator:
    llm = FakeLlm(classes={"no hot water": HOT_WATER})
    graph = LangGraphTriage(
        llm,
        store or PgTriageStore(engine),
        oct_19(),
        POLICY,
        GuideAnswerer(llm, demo_guide(), RECEPTION),
        tickets,
    )
    return RunCoordinator(engine, graph, oct_19(), LEASE)


async def add_message(engine: AsyncEngine, case_id: int) -> None:
    async with engine.begin() as conn:
        await MessageRepository(conn).insert(uuid4(), case_id, "no hot water")


async def test_i4_second_report_sees_first(async_db: AsyncEngine) -> None:
    store = PgTriageStore(async_db)
    first = await scoped_case(async_db, "m1/t0")
    second = await scoped_case(async_db, "m2/t0")
    saved: dict[int, SavedReport] = {}

    async def report(case_id: int, step_id: str) -> None:
        draft = ReportDraft("C12", FaultType.HOT_WATER, step_id, "no hot water", oct_19().now())
        saved[case_id] = await store.save_report(case_id, draft)

    # Both reports read before either inserts unless the cabin lock orders them: the inserts
    # wait on the task rows this test holds.
    async with async_db.connect() as holder:
        await holder.execute(text("SELECT id FROM tasks FOR UPDATE"))
        async with anyio.create_task_group() as tg:
            tg.start_soon(report, first, "m1/t0")
            tg.start_soon(report, second, "m2/t0")
            await wait_for(async_db, 2)
            await holder.commit()

    checked = sorted(([r.id for r in s.checked_against] for s in saved.values()), key=len)
    ids = {s.id for s in saved.values()}
    assert checked[0] == []
    assert len(checked[1]) == 1 and checked[1][0] in ids


async def test_i3_crash_after_create_one_ticket(db: Engine, async_db: AsyncEngine) -> None:
    class CrashAfterCreate:
        def __init__(self, inner: TicketPort) -> None:
            self._inner = inner
            self.crashed = False

        async def create(self, request: TicketRequest) -> TicketReceipt:
            receipt = await self._inner.create(request)
            if not self.crashed:
                self.crashed = True
                raise RuntimeError("crash")
            return receipt

    case_id = await scoped_case(async_db)
    await add_message(async_db, case_id)
    coordinator = triage(async_db, CrashAfterCreate(DemoTickets(async_db)))

    with pytest.raises(RuntimeError, match="crash"):
        await coordinator.drive(case_id)
    await coordinator.drive(case_id)

    assert count(db, "demo_tickets") == 1
    assert rows(db, "SELECT state, ticket_ref FROM tasks") == [("ticketed", "T1")]


async def test_i5_ticket_cabin_is_case_cabin(async_db: AsyncEngine) -> None:
    store = PgTriageStore(async_db)
    case_id = await scoped_case(async_db, "m1/t0")
    c14 = TicketLink("T1", TicketStatus.OPEN, 1, "C14")
    move = TaskTransition("m1/t0", TaskState.TICKETED, TaskState.QUEUED, ticket=c14)

    with pytest.raises(IntegrityError, match="fk_tasks_case_cabin"):
        await store.commit(
            case_id, StepRecord(AuditEntry("ticket", "created"), transitions=(move,))
        )


async def park(engine: AsyncEngine, case_id: int) -> bool:
    async with engine.connect() as conn:
        case = await CaseRepository(conn).get(case_id)
    async with engine.begin() as conn:
        return await CaseRepository(conn).save_status(
            case_id, case.status.park(StateReason.SPAM), case.version
        )


async def test_i8_park_before_create_no_ticket(db: Engine, async_db: AsyncEngine) -> None:
    class ParkBeforeLock(PgTriageStore):
        # Parks the case after the args passed validation and before the ticket is created.
        @asynccontextmanager
        async def lock_case(self, case_id: int) -> AsyncIterator[PgLockedCase]:
            assert await park(async_db, case_id)
            async with super().lock_case(case_id) as locked:
                yield locked

    case_id = await scoped_case(async_db)
    await add_message(async_db, case_id)

    await triage(async_db, DemoTickets(async_db), ParkBeforeLock(async_db)).drive(case_id)

    assert count(db, "demo_tickets") == 0
    assert rows(db, "SELECT state, state_reason FROM cases") == [("parked", "spam")]
    assert rows(db, "SELECT state, ticket_ref FROM tasks") == [("queued", None)]
    assert audit(db)[-1] == ("ticket", "stopped_parked")


async def test_i8_park_during_create_refused(db: Engine, async_db: AsyncEngine) -> None:
    parked: list[bool] = []

    class ParkDuringCreate:
        def __init__(self, inner: TicketPort, tg: TaskGroup) -> None:
            self._inner = inner
            self._tg = tg

        # A second connection parks the case while the ticket is being created and saved.
        async def create(self, request: TicketRequest) -> TicketReceipt:
            async def attempt() -> None:
                parked.append(await park(async_db, request.key.case_id))

            self._tg.start_soon(attempt)
            with anyio.move_on_after(2):
                await wait_for(async_db, 1)
            return await self._inner.create(request)

    case_id = await scoped_case(async_db)
    await add_message(async_db, case_id)

    async with anyio.create_task_group() as tg:
        tickets = ParkDuringCreate(DemoTickets(async_db), tg)
        await triage(async_db, tickets).drive(case_id)

    assert parked == [False]
    assert rows(db, "SELECT state FROM cases") == [("open",)]
    assert rows(db, "SELECT state, ticket_ref FROM tasks") == [("ticketed", "T1")]

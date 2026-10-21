from datetime import timedelta
from uuid import uuid4

import anyio
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from camp_agent.db.cases import CaseRepository
from camp_agent.db.messages import MessageRepository
from camp_agent.db.tasks import TaskRepository
from camp_agent.db.triage_store import PgTriageStore
from camp_agent.db.verification import VerificationRepository
from camp_agent.domain.cases import CaseState, StateReason
from camp_agent.domain.faults import FaultType
from camp_agent.domain.routing import Category, Scope, ScopeSource, TaskKind, TaskState, Urgency
from camp_agent.graph.guide_answerer import GuideAnswerer
from camp_agent.graph.langgraph_triage import LangGraphTriage
from camp_agent.graph.triage import BatchOutcome, PendingMessage, TaskDraft
from camp_agent.intake.runs import RunCoordinator
from camp_agent.intake.step_up import StepUpCommand, StepUpLimits, StepUpResult, SubmitStepUp
from camp_agent.ticket.demo_tickets import DemoTickets
from tests.fakes import FakeLlm, demo_guide, demo_stays, oct_19
from tests.unit.triage_support import C12, POLICY, RECEPTION

pytestmark = pytest.mark.anyio

LIMITS = StepUpLimits(3, 3, timedelta(hours=1))
LEASE = timedelta(seconds=120)
WAITING_CASE_UPDATES = text(
    "SELECT count(*) FROM pg_stat_activity"
    " WHERE wait_event_type = 'Lock' AND query LIKE 'UPDATE cases%'"
)
FAULT = TaskDraft(
    "m9/t0",
    TaskKind.FAULT,
    Category.MAINTENANCE,
    Urgency.URGENT,
    TaskState.AWAITING_SCOPE,
    "no hot water",
    FaultType.HOT_WATER,
)


class GatedTriage:
    def __init__(self, inner: LangGraphTriage) -> None:
        self._inner = inner
        self.entered = anyio.Event()
        self.gate = anyio.Event()

    async def resume(self, case_id: int) -> None:
        await self._inner.resume(case_id)

    async def run(self, case_id: int, batch: list[PendingMessage]) -> BatchOutcome:
        self.entered.set()
        await self.gate.wait()
        return await self._inner.run(case_id, batch)


async def new_case(engine: AsyncEngine, token: str) -> int:
    async with engine.begin() as conn:
        return (await CaseRepository(conn).create(token, None)).id


def wrong_ref(token: str, ip: str) -> StepUpCommand:
    return StepUpCommand(token, "Müller", "BK-99999", None, ip)


async def wait_for(engine: AsyncEngine, waiting: int) -> None:
    with anyio.fail_after(5):
        while True:
            async with engine.connect() as conn:
                if (await conn.execute(WAITING_CASE_UPDATES)).scalar_one() >= waiting:
                    return
            await anyio.sleep(0.01)


async def test_i10_two_failures_at_once_park(async_db: AsyncEngine) -> None:
    case_id = await new_case(async_db, "k1")
    submit = SubmitStepUp(async_db, demo_stays(), oct_19(), LIMITS)
    first = await submit(wrong_ref("k1", "ip-a"))
    assert first is not None
    assert first.result is StepUpResult.NO_MATCH
    results: list[StepUpResult] = []

    async def attempt(ip: str) -> None:
        reply = await submit(wrong_ref("k1", ip))
        assert reply is not None
        results.append(reply.result)

    # Both attempts count their failure, then wait on the case row this test holds.
    async with async_db.connect() as holder:
        await holder.execute(
            text("SELECT id FROM cases WHERE id = :id FOR NO KEY UPDATE"), {"id": case_id}
        )
        async with anyio.create_task_group() as tg:
            tg.start_soon(attempt, "ip-b")
            tg.start_soon(attempt, "ip-c")
            await wait_for(async_db, 2)
            await holder.commit()

    async with async_db.connect() as conn:
        case = await CaseRepository(conn).get(case_id)
        failures = await VerificationRepository(conn).count_failures(case_id)
    assert (case.status.state, case.status.reason) == (CaseState.PARKED, StateReason.VERIFICATION)
    assert failures == 3
    assert sorted(results) == [StepUpResult.LOCKED, StepUpResult.NO_MATCH]


async def test_us7_step_up_during_run_resumed(async_db: AsyncEngine) -> None:
    case_id = await new_case(async_db, "k1")
    store = PgTriageStore(async_db)
    llm = FakeLlm()
    triage = LangGraphTriage(
        llm,
        store,
        oct_19(),
        POLICY,
        GuideAnswerer(llm, demo_guide(), RECEPTION),
        DemoTickets(async_db),
    )
    graph = GatedTriage(triage)
    coordinator = RunCoordinator(async_db, graph, oct_19(), LEASE)
    async with async_db.begin() as conn:
        await TaskRepository(conn).insert(case_id, [FAULT])
        await MessageRepository(conn).insert(uuid4(), case_id, "where is the pool")

    async with anyio.create_task_group() as tg:
        tg.start_soon(coordinator.drive, case_id)
        await graph.entered.wait()
        async with async_db.begin() as conn:
            step_up = Scope(C12.cabin, C12.stay_from, C12.stay_to, ScopeSource.STEP_UP)
            assert await CaseRepository(conn).set_scope(case_id, step_up, 0)
        with anyio.fail_after(5):
            await coordinator.drive(case_id)
        graph.gate.set()

    async with async_db.connect() as conn:
        assert not await TaskRepository(conn).has_awaiting_scope(case_id)

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from camp_agent.db.case_repository import CaseRepository
from camp_agent.db.message_repository import MessageRepository
from camp_agent.graph.triage_graph import PendingMessage
from camp_agent.intake.run_coordinator import RunCoordinator
from tests.fakes import oct_19

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 10, 19, 14, tzinfo=UTC)
LEASE = timedelta(seconds=120)


class GatedGraph:
    def __init__(self) -> None:
        self.batches: list[list[str]] = []
        self.active = 0
        self.max_active = 0
        self.entered = anyio.Event()
        self.gate = anyio.Event()

    async def resume(self, case_id: int) -> None:
        pass

    async def run(self, case_id: int, batch: list[PendingMessage]) -> None:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.batches.append([message.text for message in batch])
        self.entered.set()
        await self.gate.wait()
        self.active -= 1


async def new_case(engine: AsyncEngine) -> int:
    async with engine.begin() as conn:
        return (await CaseRepository(conn).create(uuid4().hex, None)).id


async def claim(engine: AsyncEngine, case_id: int, owner: UUID, now: datetime) -> bool:
    async with engine.begin() as conn:
        return await CaseRepository(conn).claim_run(case_id, owner, now, now + LEASE)


async def release(engine: AsyncEngine, case_id: int, owner: UUID) -> None:
    async with engine.begin() as conn:
        await CaseRepository(conn).release_run(case_id, owner)


async def add_message(engine: AsyncEngine, case_id: int, text: str) -> None:
    async with engine.begin() as conn:
        await MessageRepository(conn).insert(uuid4(), case_id, text)


async def test_i2_two_claims_one_wins(async_db: AsyncEngine) -> None:
    case_id = await new_case(async_db)
    results: list[bool] = []

    async def attempt() -> None:
        results.append(await claim(async_db, case_id, uuid4(), NOW))

    async with anyio.create_task_group() as tg:
        tg.start_soon(attempt)
        tg.start_soon(attempt)

    assert sorted(results) == [False, True]


async def test_i2_expired_lease_reclaimed(async_db: AsyncEngine) -> None:
    case_id = await new_case(async_db)
    assert await claim(async_db, case_id, uuid4(), NOW)

    assert not await claim(async_db, case_id, uuid4(), NOW + LEASE - timedelta(seconds=1))
    assert await claim(async_db, case_id, uuid4(), NOW + LEASE)


async def test_i2_only_owner_releases(async_db: AsyncEngine) -> None:
    case_id = await new_case(async_db)
    owner = uuid4()
    assert await claim(async_db, case_id, owner, NOW)

    await release(async_db, case_id, uuid4())
    assert not await claim(async_db, case_id, uuid4(), NOW)

    await release(async_db, case_id, owner)
    assert await claim(async_db, case_id, uuid4(), NOW)


async def test_us2_message_mid_run_queues(async_db: AsyncEngine) -> None:
    case_id = await new_case(async_db)
    graph = GatedGraph()
    coordinator = RunCoordinator(async_db, graph, oct_19(), LEASE)
    await add_message(async_db, case_id, "where is the pool")

    async with anyio.create_task_group() as tg:
        tg.start_soon(coordinator.drive, case_id)
        await graph.entered.wait()
        await add_message(async_db, case_id, "also the heater is off")
        with anyio.fail_after(5):
            await coordinator.drive(case_id)
        assert graph.batches == [["where is the pool"]]
        graph.gate.set()

    assert graph.batches == [["where is the pool"], ["also the heater is off"]]
    assert graph.max_active == 1
    async with async_db.connect() as conn:
        assert not await MessageRepository(conn).has_pending(case_id)

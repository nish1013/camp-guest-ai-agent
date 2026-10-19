from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncEngine

from camp_agent.clock import Clock
from camp_agent.db.case_repository import CaseRepository
from camp_agent.db.message_repository import MessageRepository
from camp_agent.db.task_repository import TaskRepository
from camp_agent.domain.case_state import CaseState
from camp_agent.domain.step_up import resumes_waiting
from camp_agent.graph.triage_graph import BatchOutcome, TriageGraph, next_batch


class RunCoordinator:
    def __init__(
        self, engine: AsyncEngine, graph: TriageGraph, clock: Clock, lease: timedelta
    ) -> None:
        self._engine = engine
        self._graph = graph
        self._clock = clock
        self._lease = lease

    async def drive(self, case_id: int) -> None:
        owner = uuid4()
        while await self._claim(case_id, owner):
            try:
                await self._graph.resume(case_id)
                await self._run_pending(case_id)
            finally:
                await self._release(case_id, owner)
            # A message or a step-up saved while this run held the lease found the case busy and
            # did not start a run of its own, so it is picked up here.
            if not await self._has_work(case_id):
                return

    async def _run_pending(self, case_id: int) -> None:
        while True:
            async with self._engine.connect() as conn:
                pending = await MessageRepository(conn).pending(case_id)
            if not pending:
                return
            batch = next_batch(pending)
            outcome = await self._graph.run(case_id, batch)
            async with self._engine.begin() as conn:
                await MessageRepository(conn).mark_handled(
                    [message.id for message in batch],
                    self._clock.now(),
                    parked=outcome is BatchOutcome.PARKED,
                )

    async def _claim(self, case_id: int, owner: UUID) -> bool:
        now = self._clock.now()
        async with self._engine.begin() as conn:
            return await CaseRepository(conn).claim_run(case_id, owner, now, now + self._lease)

    async def _release(self, case_id: int, owner: UUID) -> None:
        async with self._engine.begin() as conn:
            await CaseRepository(conn).release_run(case_id, owner)

    async def _has_work(self, case_id: int) -> bool:
        async with self._engine.connect() as conn:
            if await MessageRepository(conn).has_pending(case_id):
                return True
            case = await CaseRepository(conn).get(case_id)
            tasks = TaskRepository(conn)
            if resumes_waiting(case.status, case.scope) and await tasks.has_awaiting_scope(case_id):
                return True
            if case.status.state is CaseState.PARKED:
                return False
            return await tasks.has_actionable(case_id)

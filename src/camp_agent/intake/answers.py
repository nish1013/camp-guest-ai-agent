from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine

from camp_agent.clock import Clock
from camp_agent.db.audit import AuditRepository
from camp_agent.db.cases import CaseRecord, CaseRepository
from camp_agent.db.tasks import TaskRepository
from camp_agent.domain.cases import AuditEntry, CaseState, StateReason
from camp_agent.domain.faults import Confirmation, after_answer, answered
from camp_agent.domain.routing import TaskState
from camp_agent.graph.triage import StaleCaseError, TaskTransition


@dataclass(frozen=True)
class AnswerCommand:
    case_token: str
    confirmation: Confirmation
    subject: str
    yes: bool


@dataclass(frozen=True)
class AnswerReply:
    case: CaseRecord
    # The answer moved a waiting task, so a run must pick it up.
    moved: bool


_CONFLICT_ATTEMPTS = 5


class SubmitAnswer:
    def __init__(self, engine: AsyncEngine, clock: Clock) -> None:
        self._engine = engine
        self._clock = clock

    async def __call__(self, command: AnswerCommand) -> AnswerReply | None:
        for _ in range(_CONFLICT_ATTEMPTS):
            async with self._engine.connect() as conn:
                case = await CaseRepository(conn).find_open_by_token(command.case_token)
            if case is None:
                return None
            if case.status.state is CaseState.PARKED:
                return AnswerReply(case, moved=False)
            try:
                moved = await self._apply(case, command)
            except StaleCaseError:
                continue
            async with self._engine.connect() as conn:
                return AnswerReply(await CaseRepository(conn).get(case.id), moved)
        raise RuntimeError("the case kept changing while an answer was saved")

    async def _apply(self, case: CaseRecord, command: AnswerCommand) -> bool:
        async with self._engine.begin() as conn:
            tasks = TaskRepository(conn)
            waiting = answered(await tasks.faults(case.id), command.confirmation, command.subject)
            if not waiting:
                return False
            target = after_answer(command.confirmation, command.yes)
            for fault in waiting:
                await tasks.transition(case.id, TaskTransition(fault.step_id, target, fault.state))
            status = case.status
            if target is TaskState.HELD:
                status = status.hold(StateReason.FAULT_REVIEW, self._clock.now())
            # The version moves on every answer, so a run that read the case before it retries.
            if not await CaseRepository(conn).save_status(case.id, status, case.version):
                raise StaleCaseError(case.id)
            audit = AuditEntry(
                f"answer_{command.confirmation}",
                "yes" if command.yes else "no",
                {"step_ids": [fault.step_id for fault in waiting]},
            )
            await AuditRepository(conn).insert(case.id, audit)
        return True

from sqlalchemy.ext.asyncio import AsyncEngine

from camp_agent.clock import Clock
from camp_agent.db.staff_rows import Resolution
from camp_agent.db.task_repository import TaskRepository
from camp_agent.domain.audit_entry import AuditEntry, AuditValue
from camp_agent.domain.case_closure import settled
from camp_agent.domain.case_state import CaseState
from camp_agent.domain.route_guard import TaskState
from camp_agent.domain.staff_resolution import approved_state, edit_errors
from camp_agent.notification.case_watch import CaseWatch
from camp_agent.staff.resolve_error import ResolveError
from camp_agent.staff.staff_case_lock import StaffCase, StaffCaseLock
from camp_agent.staff.staff_conflict_error import StaffConflictError
from camp_agent.staff.staff_types import ResolveCommand

RESOLVE = "resolve"


class ResolveAsHuman:
    def __init__(self, engine: AsyncEngine, clock: Clock, watch: CaseWatch | None = None) -> None:
        self._lock = StaffCaseLock(engine, clock, watch)
        self._clock = clock

    # Returns False when no such case exists.
    async def __call__(self, command: ResolveCommand) -> bool:
        async with self._lock(command.case_id, command.version) as staff:
            if staff is None:
                return False
            if staff.case.status.state is not CaseState.HELD:
                raise StaffConflictError(command.case_id)
            detail = await self._resolve_task(staff, command)
            status = staff.case.status
            if command.urgency is not None:
                status = status.raise_urgency(command.urgency)
            if not await TaskRepository(staff.conn).held(command.case_id):
                status = status.release()
            status = settled(status, await staff.progress(), self._clock.now())
            detail["case"] = status.state
            decision = "approved" if command.approve else "rejected"
            await staff.save(status, AuditEntry(RESOLVE, decision, detail))
        return True

    async def _resolve_task(
        self, staff: StaffCase, command: ResolveCommand
    ) -> dict[str, AuditValue]:
        tasks = TaskRepository(staff.conn)
        held = {task.step_id: task for task in await tasks.held(command.case_id)}
        edited = command.category is not None or command.urgency is not None
        if command.step_id is None:
            if held or edited:
                raise ResolveError("choose the held task to resolve")
            return {}
        task = held.get(command.step_id)
        if task is None:
            # Resolved by someone else since the page was read.
            raise StaffConflictError(command.case_id)
        errors = edit_errors(task.kind, command.category, edited)
        if errors:
            raise ResolveError("; ".join(errors))
        state = approved_state(task.kind, task.reported) if command.approve else TaskState.REJECTED
        await tasks.resolve(
            command.case_id, task.step_id, Resolution(state, command.category, command.urgency)
        )
        detail: dict[str, AuditValue] = {"step_id": task.step_id, "state": state}
        if command.category is not None:
            detail["category"] = command.category
        if command.urgency is not None:
            detail["urgency"] = command.urgency
        return detail

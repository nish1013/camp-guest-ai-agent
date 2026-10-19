from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from camp_agent.clock import Clock
from camp_agent.db.audit_repository import AuditRepository
from camp_agent.db.case_repository import CaseRepository
from camp_agent.db.task_repository import TaskRepository
from camp_agent.db.ticket_event_repository import TicketEventRepository
from camp_agent.db.ticket_lock import lock_ticket, unlock_ticket
from camp_agent.domain.audit_entry import AuditEntry, AuditValue
from camp_agent.domain.case_closure import settled
from camp_agent.domain.run_lease import run_active
from camp_agent.ticket.ticket_types import TicketStatusChanged

TICKET_STATUS = "ticket_status"
_BATCH = 100


class ApplyTicketStatus:
    def __init__(self, engine: AsyncEngine, clock: Clock) -> None:
        self._engine = engine
        self._clock = clock

    # Repeats and late events are harmless, so two passes at once need no lock (D45).
    async def handle_pending(self) -> None:
        async with self._engine.connect() as conn:
            rows = await TicketEventRepository(conn).oldest(_BATCH)
        for row in rows:
            if await self._apply(row.event):
                async with self._engine.begin() as conn:
                    await TicketEventRepository(conn).delete(row.id)

    # The ticket lock orders this pass against a task taking the ticket ref: either the task
    # is listed here, or it copies the status this pass applied.
    async def _apply(self, event: TicketStatusChanged) -> bool:
        async with self._engine.connect() as conn:
            await lock_ticket(conn, event.ticket_ref)
            await conn.commit()
            try:
                case_ids = await TaskRepository(conn).cases_with_ticket(event.ticket_ref)
                await conn.commit()
                # No task holds the ref yet: its create is still committing, so keep the event.
                applied = bool(case_ids)
                for case_id in case_ids:
                    applied = await self._apply_to_case(conn, case_id, event) and applied
            finally:
                await unlock_ticket(conn, event.ticket_ref)
                await conn.commit()
        return applied

    # One case per transaction (US13). Returns False when a run holds the case: the event
    # stays in the outbox for the next pass.
    async def _apply_to_case(
        self, conn: AsyncConnection, case_id: int, event: TicketStatusChanged
    ) -> bool:
        now = self._clock.now()
        async with conn.begin():
            cases = CaseRepository(conn)
            case = await cases.lock(case_id)
            if run_active(case.run_lease_until, now):
                return False
            tasks = TaskRepository(conn)
            if not await tasks.apply_ticket_status(case_id, event):
                return True
            status = settled(case.status, await tasks.progress(case_id), now)
            if not await cases.save_status(case_id, status, case.version):
                raise RuntimeError("a locked case changed")
            detail: dict[str, AuditValue] = {
                "ticket": event.ticket_ref,
                "version": event.version,
                "case": status.state,
            }
            await AuditRepository(conn).insert(
                case_id, AuditEntry(TICKET_STATUS, event.status, detail)
            )
        return True

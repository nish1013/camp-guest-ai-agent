import logging
from enum import Enum

import anyio
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from camp_agent.clock import Clock
from camp_agent.db.audit import AuditRepository
from camp_agent.db.cases import CaseRepository
from camp_agent.db.tasks import TaskRepository
from camp_agent.db.tickets import TicketEventRepository, lock_ticket, unlock_ticket
from camp_agent.domain.cases import AuditEntry, AuditValue, run_active, settled
from camp_agent.notification.port import CaseWatch
from camp_agent.ticket.port import TicketStatusChanged

TICKET_STATUS = "ticket_status"


class _Outcome(Enum):
    APPLIED = "applied"
    IGNORED = "ignored"
    BUSY = "busy"


_BATCH = 100


class ApplyTicketStatus:
    def __init__(self, engine: AsyncEngine, clock: Clock, watch: CaseWatch | None = None) -> None:
        self._engine = engine
        self._clock = clock
        self._watch = watch

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
        changed: list[int] = []
        async with self._engine.connect() as conn:
            await lock_ticket(conn, event.ticket_ref)
            await conn.commit()
            try:
                case_ids = await TaskRepository(conn).cases_with_ticket(event.ticket_ref)
                await conn.commit()
                # No task holds the ref yet: its create is still committing, so keep the event.
                applied = bool(case_ids)
                for case_id in case_ids:
                    outcome = await self._apply_to_case(conn, case_id, event)
                    applied = outcome is not _Outcome.BUSY and applied
                    if outcome is _Outcome.APPLIED:
                        changed.append(case_id)
            finally:
                await unlock_ticket(conn, event.ticket_ref)
                await conn.commit()
        if self._watch is not None:
            for case_id in changed:
                await self._watch.changed(case_id)
        return applied

    # One case per transaction (US13). BUSY when a run holds the case: the event stays in the
    # outbox for the next pass. A repeat or late event is IGNORED by the version check.
    async def _apply_to_case(
        self, conn: AsyncConnection, case_id: int, event: TicketStatusChanged
    ) -> _Outcome:
        now = self._clock.now()
        async with conn.begin():
            cases = CaseRepository(conn)
            case = await cases.lock(case_id)
            if run_active(case.run_lease_until, now):
                return _Outcome.BUSY
            tasks = TaskRepository(conn)
            if not await tasks.apply_ticket_status(case_id, event):
                return _Outcome.IGNORED
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
        return _Outcome.APPLIED


log = logging.getLogger(__name__)


class OutboxPoller:
    def __init__(self, handler: ApplyTicketStatus, interval_s: float) -> None:
        self._handler = handler
        self._interval_s = interval_s

    async def run(self) -> None:
        while True:
            try:
                await self._handler.handle_pending()
            except Exception:
                # The outbox keeps every unhandled event, so the next pass retries it.
                log.exception("ticket status pass failed")
            await anyio.sleep(self._interval_s)

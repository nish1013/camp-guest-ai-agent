from collections.abc import Sequence

from sqlalchemy import ColumnElement, and_, func, insert, or_, select
from sqlalchemy.ext.asyncio import AsyncConnection

from camp_agent.db.tables import reports, tasks
from camp_agent.domain.faults import (
    CLOSED_TICKET_STATES,
    FaultType,
    OpenReport,
    ReportDraft,
    SavedReport,
    TicketStatus,
)
from camp_agent.graph.triage import LinkTarget

# First key of the two-key advisory lock: keeps cabin locks apart from any other lock.
_CABIN_LOCK = 4


_TASK = and_(tasks.c.case_id == reports.c.case_id, tasks.c.step_id == reports.c.step_id)


_OPEN: ColumnElement[bool] = or_(
    tasks.c.ticket_status.is_(None), tasks.c.ticket_status.not_in(CLOSED_TICKET_STATES)
)


class ReportRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    # Call inside a transaction: the lock is held until it ends.
    async def save(self, case_id: int, draft: ReportDraft) -> SavedReport:
        await self._conn.execute(
            select(func.pg_advisory_xact_lock(_CABIN_LOCK, func.hashtext(draft.cabin)))
        )
        saved = await self._find(case_id, draft.step_id)
        if saved is not None:
            return saved
        earlier = await self._open(reports.c.cabin == draft.cabin)
        report_id: int = (
            await self._conn.execute(
                insert(reports)
                .values(
                    cabin=draft.cabin,
                    fault_type=draft.fault_type,
                    case_id=case_id,
                    step_id=draft.step_id,
                    summary=draft.summary,
                    checked_against=[report.id for report in earlier],
                    created_at=draft.at,
                )
                .returning(reports.c.id)
            )
        ).scalar_one()
        return SavedReport(report_id, tuple(earlier))

    async def get(self, report_id: int) -> OpenReport:
        query = select(
            reports.c.id, reports.c.fault_type, reports.c.summary, reports.c.created_at
        ).where(reports.c.id == report_id)
        row = (await self._conn.execute(query)).one()
        return OpenReport(row.id, FaultType(row.fault_type), row.summary, row.created_at)

    async def link_target(self, report_id: int) -> LinkTarget | None:
        query = (
            select(tasks.c.ticket_ref, tasks.c.ticket_status, tasks.c.ticket_version, tasks.c.cabin)
            .join(reports, _TASK)
            .where(reports.c.id == report_id)
        )
        row = (await self._conn.execute(query)).one_or_none()
        if row is None:
            return None
        status = None if row.ticket_status is None else TicketStatus(row.ticket_status)
        return LinkTarget(row.ticket_ref, status, row.ticket_version, row.cabin)

    async def _find(self, case_id: int, step_id: str) -> SavedReport | None:
        query = select(reports.c.id, reports.c.checked_against).where(
            reports.c.case_id == case_id, reports.c.step_id == step_id
        )
        row = (await self._conn.execute(query)).one_or_none()
        if row is None:
            return None
        checked: Sequence[int] = row.checked_against
        earlier = await self._open(reports.c.id.in_(checked)) if checked else []
        return SavedReport(row.id, tuple(earlier))

    async def _open(self, where: ColumnElement[bool]) -> list[OpenReport]:
        query = (
            select(reports.c.id, reports.c.fault_type, reports.c.summary, reports.c.created_at)
            .join(tasks, _TASK)
            .where(where, _OPEN)
            .order_by(reports.c.id)
        )
        rows = (await self._conn.execute(query)).all()
        return [
            OpenReport(row.id, FaultType(row.fault_type), row.summary, row.created_at)
            for row in rows
        ]

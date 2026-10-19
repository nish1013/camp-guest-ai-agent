from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Row, insert, or_, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from camp_agent.db.case_record import CaseRecord
from camp_agent.db.tables import cases
from camp_agent.domain.case_state import LIVE_STATES, CaseState, StateReason
from camp_agent.domain.case_status import CaseStatus
from camp_agent.domain.scope import Scope, ScopeSource
from camp_agent.domain.urgency import Urgency


class CaseRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def get(self, case_id: int) -> CaseRecord:
        row = (await self._conn.execute(select(cases).where(cases.c.id == case_id))).one()
        return self._record(row)

    async def find_open_by_token(self, case_token: str) -> CaseRecord | None:
        query = select(cases).where(
            cases.c.case_token == case_token, cases.c.state.in_(LIVE_STATES)
        )
        row = (await self._conn.execute(query)).one_or_none()
        return None if row is None else self._record(row)

    async def create(self, case_token: str, scope: Scope | None) -> CaseRecord:
        values: dict[str, Any] = {"case_token": case_token, "state": CaseState.OPEN, "version": 0}
        if scope is not None:
            values |= {
                "scope_cabin": scope.cabin,
                "scope_stay_from": scope.stay_from,
                "scope_stay_to": scope.stay_to,
                "scope_source": scope.source,
            }
        row = (await self._conn.execute(insert(cases).values(values).returning(cases))).one()
        return self._record(row)

    async def save_status(self, case_id: int, status: CaseStatus, version: int) -> bool:
        return await self._update_at_version(
            case_id,
            version,
            {
                "state": status.state,
                "state_reason": status.reason,
                "safety": status.safety,
                "urgency": status.urgency,
                "clarify_rounds": status.clarify_rounds,
                "held_at": status.held_at,
            },
        )

    async def set_scope(self, case_id: int, scope: Scope, version: int) -> bool:
        return await self._update_at_version(
            case_id,
            version,
            {
                "scope_cabin": scope.cabin,
                "scope_stay_from": scope.stay_from,
                "scope_stay_to": scope.stay_to,
                "scope_source": scope.source,
            },
        )

    async def bump_version(self, case_id: int, version: int) -> bool:
        return await self._update_at_version(case_id, version, {})

    async def claim_run(self, case_id: int, owner: UUID, now: datetime, until: datetime) -> bool:
        claimed = await self._conn.execute(
            update(cases)
            .where(
                cases.c.id == case_id,
                or_(cases.c.run_lease_until.is_(None), cases.c.run_lease_until <= now),
            )
            .values(run_lease_owner=owner, run_lease_until=until)
            .returning(cases.c.id)
        )
        return claimed.one_or_none() is not None

    async def release_run(self, case_id: int, owner: UUID) -> None:
        await self._conn.execute(
            update(cases)
            .where(cases.c.id == case_id, cases.c.run_lease_owner == owner)
            .values(run_lease_owner=None, run_lease_until=None)
        )

    async def _update_at_version(self, case_id: int, version: int, values: dict[str, Any]) -> bool:
        updated = await self._conn.execute(
            update(cases)
            .where(cases.c.id == case_id, cases.c.version == version)
            .values(**values, version=cases.c.version + 1)
            .returning(cases.c.id)
        )
        return updated.one_or_none() is not None

    def _record(self, row: Row[Any]) -> CaseRecord:
        scope = None
        if row.scope_cabin is not None:
            scope = Scope(
                row.scope_cabin,
                row.scope_stay_from,
                row.scope_stay_to,
                ScopeSource(row.scope_source),
            )
        status = CaseStatus(
            state=CaseState(row.state),
            reason=None if row.state_reason is None else StateReason(row.state_reason),
            safety=row.safety,
            urgency=Urgency(row.urgency),
            clarify_rounds=row.clarify_rounds,
            held_at=row.held_at,
        )
        return CaseRecord(row.id, row.case_token, status, scope, row.version)

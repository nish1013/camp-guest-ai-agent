import secrets
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from camp_agent.clock import Clock
from camp_agent.db.audit import AuditRepository
from camp_agent.db.cases import CaseRecord, CaseRepository
from camp_agent.db.messages import MessageRepository
from camp_agent.domain.cases import AuditEntry, CaseState, reopens
from camp_agent.domain.guest_status import QuickPick
from camp_agent.domain.routing import Scope
from camp_agent.domain.safety import SafetyRule, mask_pii


@dataclass(frozen=True)
class SubmitMessageCommand:
    text: str
    idempotency_key: UUID
    case_token: str | None
    scope: Scope | None
    client_ip: str
    qr_invalid: bool = False
    pick: QuickPick | None = None


@dataclass(frozen=True)
class Accepted:
    case: CaseRecord
    replayed: bool


@dataclass(frozen=True)
class RateLimited:
    pass


type SubmitResult = Accepted | RateLimited


class SlidingWindowLimiter:
    def __init__(self, max_events: int, window: timedelta) -> None:
        self._max = max_events
        self._window = window
        self._events: dict[str, deque[datetime]] = {}
        self._last_sweep: datetime | None = None

    def allow(self, keys: list[str], now: datetime) -> bool:
        cutoff = now - self._window
        self._sweep_if_due(now, cutoff)
        for key in keys:
            self._prune(key, cutoff)
        if any(len(self._events.get(key, ())) >= self._max for key in keys):
            return False
        for key in keys:
            self._events.setdefault(key, deque()).append(now)
        return True

    def _prune(self, key: str, cutoff: datetime) -> None:
        events = self._events.get(key)
        if events is None:
            return
        while events and events[0] <= cutoff:
            events.popleft()
        if not events:
            del self._events[key]

    def _sweep_if_due(self, now: datetime, cutoff: datetime) -> None:
        if self._last_sweep is not None and now - self._last_sweep < self._window:
            return
        self._last_sweep = now
        for key in list(self._events):
            self._prune(key, cutoff)


INVALID_QR = AuditEntry("qr_scope", "invalid_token")


REOPENED = AuditEntry("case", "reopened")


class SubmitMessage:
    def __init__(
        self,
        engine: AsyncEngine,
        limiter: SlidingWindowLimiter,
        clock: Clock,
        safety: SafetyRule,
        reopen_window: timedelta,
    ) -> None:
        self._engine = engine
        self._limiter = limiter
        self._clock = clock
        self._safety = safety
        self._reopen_window = reopen_window

    async def __call__(self, command: SubmitMessageCommand) -> SubmitResult:
        replay = await self._replay(command)
        if replay is not None:
            return replay
        text = mask_pii(command.text)
        # A safety message is never refused (D8), so it is checked before the limit is.
        if not self._safety.hits(text) and not self._limiter.allow(
            self._limit_keys(command), self._clock.now()
        ):
            return RateLimited()

        async with self._engine.connect() as conn:
            tx = await conn.begin()
            cases = CaseRepository(conn)
            case = None
            if command.case_token is not None:
                case = await self._joinable(conn, command.case_token)
            # A pick belongs to a new request (D51); a message joining a case carries none.
            pick = None
            if case is None:
                case = await cases.create(secrets.token_urlsafe(32), command.scope)
                pick = command.pick
            if await MessageRepository(conn).insert(command.idempotency_key, case.id, text, pick):
                if command.qr_invalid:
                    await AuditRepository(conn).insert(case.id, INVALID_QR)
                await tx.commit()
                return Accepted(case, replayed=False)
            await tx.rollback()

        replay = await self._replay(command)
        if replay is None:
            raise RuntimeError("idempotency key conflicted but no message holds it")
        return replay

    async def _joinable(self, conn: AsyncConnection, case_token: str) -> CaseRecord | None:
        cases = CaseRepository(conn)
        found = await cases.find_by_token(case_token)
        if found is None or found.status.state is not CaseState.CLOSED:
            return found
        # A reply within the window reopens the case (D20); a later one starts a new case.
        locked = await cases.lock(found.id)
        if locked.status.state is not CaseState.CLOSED:
            return locked
        if not reopens(locked.status.closed_at, self._clock.now(), self._reopen_window):
            return None
        if not await cases.save_status(locked.id, locked.status.reopen(), locked.version):
            raise RuntimeError("a locked case changed")
        await AuditRepository(conn).insert(locked.id, REOPENED)
        return await cases.get(locked.id)

    async def _replay(self, command: SubmitMessageCommand) -> Accepted | None:
        async with self._engine.connect() as conn:
            case_id = await MessageRepository(conn).find_case_id(command.idempotency_key)
            if case_id is None:
                return None
            return Accepted(await CaseRepository(conn).get(case_id), replayed=True)

    def _limit_keys(self, command: SubmitMessageCommand) -> list[str]:
        keys = [f"ip:{command.client_ip}"]
        if command.scope is not None:
            keys.append(f"cabin:{command.scope.cabin}")
        return keys

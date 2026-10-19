import secrets
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from camp_agent.clock import Clock
from camp_agent.db.audit_repository import AuditRepository
from camp_agent.db.case_record import CaseRecord
from camp_agent.db.case_repository import CaseRepository
from camp_agent.db.message_repository import MessageRepository
from camp_agent.domain.audit_entry import AuditEntry
from camp_agent.domain.case_closure import reopens
from camp_agent.domain.case_state import CaseState
from camp_agent.domain.pii_masker import mask_pii
from camp_agent.domain.safety_rule import SafetyRule
from camp_agent.intake.intake_types import Accepted, RateLimited, SubmitMessageCommand, SubmitResult
from camp_agent.intake.rate_limiter import SlidingWindowLimiter

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

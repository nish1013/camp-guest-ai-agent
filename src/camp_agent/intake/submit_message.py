import secrets

from sqlalchemy.ext.asyncio import AsyncEngine

from camp_agent.clock import Clock
from camp_agent.db.audit_repository import AuditRepository
from camp_agent.db.case_repository import CaseRepository
from camp_agent.db.message_repository import MessageRepository
from camp_agent.domain.audit_entry import AuditEntry
from camp_agent.domain.pii_masker import mask_pii
from camp_agent.domain.safety_rule import SafetyRule
from camp_agent.intake.intake_types import Accepted, RateLimited, SubmitMessageCommand, SubmitResult
from camp_agent.intake.rate_limiter import SlidingWindowLimiter

INVALID_QR = AuditEntry("qr_scope", "invalid_token")


class SubmitMessage:
    def __init__(
        self,
        engine: AsyncEngine,
        limiter: SlidingWindowLimiter,
        clock: Clock,
        safety: SafetyRule,
    ) -> None:
        self._engine = engine
        self._limiter = limiter
        self._clock = clock
        self._safety = safety

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
                case = await cases.find_open_by_token(command.case_token)
            if case is None:
                case = await cases.create(secrets.token_urlsafe(32), command.scope)
            if await MessageRepository(conn).insert(command.idempotency_key, case.id, text):
                if command.qr_invalid:
                    await AuditRepository(conn).insert(case.id, INVALID_QR)
                await tx.commit()
                return Accepted(case, replayed=False)
            await tx.rollback()

        replay = await self._replay(command)
        if replay is None:
            raise RuntimeError("idempotency key conflicted but no message holds it")
        return replay

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

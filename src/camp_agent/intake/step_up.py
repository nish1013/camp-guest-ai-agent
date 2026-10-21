import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncEngine

from camp_agent.clock import Clock
from camp_agent.db.audit import AuditRepository
from camp_agent.db.cases import CaseRecord, CaseRepository
from camp_agent.db.tasks import TaskRepository
from camp_agent.db.verification import IpFailureRepository, VerificationRepository
from camp_agent.domain.cases import AuditEntry, AuditValue, CaseState
from camp_agent.domain.step_up import (
    BookingCheck,
    asks_step_up,
    check_booking,
    limit_reached,
    normalise_ref,
    step_up_scope,
)
from camp_agent.graph.triage import StaleCaseError
from camp_agent.stay.port import Booking, StayContextPort, StayError


class StepUpResult(StrEnum):
    MATCHED = "matched"
    NO_MATCH = "no_match"
    LOCKED = "locked"
    BOOKINGS_DOWN = "bookings_down"
    ALREADY_SCOPED = "already_scoped"


@dataclass(frozen=True)
class StepUpCommand:
    case_token: str
    surname: str
    booking_ref: str
    cabin_hint: str | None
    client_ip: str


@dataclass(frozen=True)
class StepUpReply:
    result: StepUpResult
    case: CaseRecord


@dataclass(frozen=True)
class StepUpLimits:
    case_failures: int
    ip_failures: int
    ip_window: timedelta


class StepUpForm:
    def __init__(self, engine: AsyncEngine, failure_limit: int) -> None:
        self._engine = engine
        self._limit = failure_limit

    async def shown(self, case: CaseRecord) -> bool:
        if case.scope is not None:
            return False
        async with self._engine.connect() as conn:
            waiting = await TaskRepository(conn).has_awaiting_scope(case.id)
            failures = await VerificationRepository(conn).count_failures(case.id)
        return asks_step_up(case.status, case.scope, waiting, limit_reached(failures, self._limit))


STEP_UP = "step_up"


PARKED = "parked"


FAILED = "failed"


IP_LIMIT: dict[str, AuditValue] = {"check": "ip_limit"}


_CONFLICT_ATTEMPTS = 5


log = logging.getLogger(__name__)


class SubmitStepUp:
    def __init__(
        self, engine: AsyncEngine, stays: StayContextPort, clock: Clock, limits: StepUpLimits
    ) -> None:
        self._engine = engine
        self._stays = stays
        self._clock = clock
        self._limits = limits

    # Surname and ref are compared here and never stored, logged or passed on (D3).
    async def __call__(self, command: StepUpCommand) -> StepUpReply | None:
        async with self._engine.connect() as conn:
            case = await CaseRepository(conn).find_open_by_token(command.case_token)
        if case is None:
            return None
        booking: Booking | None = None
        looked_up = False
        for _ in range(_CONFLICT_ATTEMPTS):
            if case.scope is not None:
                return StepUpReply(StepUpResult.ALREADY_SCOPED, case)
            if await self._locked(case):
                return StepUpReply(StepUpResult.LOCKED, case)
            now = self._clock.now()
            try:
                if await self._ip_locked(command.client_ip, now):
                    result = await self._park_for_ip(case)
                else:
                    if not looked_up:
                        try:
                            ref = normalise_ref(command.booking_ref)
                            booking = await self._stays.find_booking(ref)
                        except StayError:
                            # Not an attempt: it does not count towards the limit (D41).
                            log.warning("stay context unavailable for a step-up")
                            return StepUpReply(StepUpResult.BOOKINGS_DOWN, case)
                        looked_up = True
                    check = check_booking(
                        booking, command.surname, command.cabin_hint, self._clock.today()
                    )
                    result = await self._record(case, check, booking, command.client_ip, now)
            except StaleCaseError:
                case = await self._reload(case.id)
                continue
            return StepUpReply(result, await self._reload(case.id))
        raise RuntimeError("the case kept changing during a step-up")

    async def _record(
        self,
        case: CaseRecord,
        check: BookingCheck,
        booking: Booking | None,
        ip: str,
        now: datetime,
    ) -> StepUpResult:
        async with self._engine.begin() as conn:
            cases = CaseRepository(conn)
            attempts = VerificationRepository(conn)
            await attempts.insert(case.id, check, now)
            if check is BookingCheck.MATCHED and booking is not None:
                scope = step_up_scope(booking)
                saved = await cases.set_scope(case.id, scope, case.version)
                audit = AuditEntry(STEP_UP, check, {"cabin": scope.cabin})
                result = StepUpResult.MATCHED
            else:
                await IpFailureRepository(conn).insert(ip, now)
                failures = await attempts.count_failures(case.id)
                parked = limit_reached(failures, self._limits.case_failures)
                # Every failure moves the version, so two failures at once cannot both miss
                # the limit (I10).
                if parked:
                    status = case.status.park_unverified()
                    saved = await cases.save_status(case.id, status, case.version)
                else:
                    saved = await cases.bump_version(case.id, case.version)
                detail: dict[str, AuditValue] = {"check": check, "failures": failures}
                audit = AuditEntry(STEP_UP, PARKED if parked else FAILED, detail)
                result = StepUpResult.LOCKED if parked else StepUpResult.NO_MATCH
            if not saved:
                raise StaleCaseError(case.id)
            await AuditRepository(conn).insert(case.id, audit)
        return result

    async def _park_for_ip(self, case: CaseRecord) -> StepUpResult:
        async with self._engine.begin() as conn:
            status = case.status.park_unverified()
            if not await CaseRepository(conn).save_status(case.id, status, case.version):
                raise StaleCaseError(case.id)
            await AuditRepository(conn).insert(case.id, AuditEntry(STEP_UP, PARKED, IP_LIMIT))
        return StepUpResult.LOCKED

    async def _locked(self, case: CaseRecord) -> bool:
        if case.status.state is CaseState.PARKED:
            return True
        async with self._engine.connect() as conn:
            failures = await VerificationRepository(conn).count_failures(case.id)
        return limit_reached(failures, self._limits.case_failures)

    async def _ip_locked(self, ip: str, now: datetime) -> bool:
        since = now - self._limits.ip_window
        async with self._engine.connect() as conn:
            failures = await IpFailureRepository(conn).count_since(ip, since)
        return limit_reached(failures, self._limits.ip_failures)

    async def _reload(self, case_id: int) -> CaseRecord:
        async with self._engine.connect() as conn:
            return await CaseRepository(conn).get(case_id)

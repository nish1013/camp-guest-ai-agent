from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine

from camp_agent.clock import Clock
from camp_agent.db.messages import MessageRepository
from camp_agent.db.tasks import TaskRepository
from camp_agent.domain.cases import AuditEntry, AuditValue, CaseState, StateReason
from camp_agent.domain.staff_resolution import restored_hold, staff_scope
from camp_agent.domain.step_up import normalise_ref
from camp_agent.notification.port import CaseWatch
from camp_agent.staff.case_lock import StaffCaseLock, StaffConflictError
from camp_agent.stay.port import Booking, StayContextPort


class RestoreError(Exception):
    pass


@dataclass(frozen=True)
class RestoreCommand:
    case_id: int
    version: int
    booking_ref: str | None = None


RESTORE = "restore"
NO_BOOKING = "No booking with that reference."
NEEDS_BOOKING = "A case parked after failed verification needs the booking reference."
HAS_SCOPE = "This case already has a cabin and stay."


class RestoreCase:
    def __init__(
        self,
        engine: AsyncEngine,
        clock: Clock,
        stays: StayContextPort,
        watch: CaseWatch | None = None,
    ) -> None:
        self._lock = StaffCaseLock(engine, clock, watch)
        self._clock = clock
        self._stays = stays

    # Returns False when no such case exists. StayError propagates: the booking system is down.
    async def __call__(self, command: RestoreCommand) -> bool:
        booking = await self._booking(command.booking_ref)
        async with self._lock(command.case_id, command.version) as staff:
            if staff is None:
                return False
            case = staff.case
            if case.status.state is not CaseState.PARKED:
                raise StaffConflictError(command.case_id)
            unverified = case.status.reason is StateReason.VERIFICATION
            if booking is not None and case.scope is not None:
                raise RestoreError(HAS_SCOPE)
            if unverified and booking is None and case.scope is None:
                raise RestoreError(NEEDS_BOOKING)
            held = await TaskRepository(staff.conn).held(case.id)
            status = case.status.restore(
                restored_hold([task.kind for task in held]), self._clock.now()
            )
            # The park stopped these messages before triage; a spam verdict is overridden.
            requeued = await MessageRepository(staff.conn).requeue_parked(
                case.id, restored=not unverified
            )
            detail: dict[str, AuditValue] = {"requeued": requeued, "case": status.state}
            scope = None if booking is None else staff_scope(booking)
            if scope is not None:
                detail["cabin"] = scope.cabin
            await staff.save(status, AuditEntry(RESTORE, str(case.status.reason), detail), scope)
        return True

    async def _booking(self, booking_ref: str | None) -> Booking | None:
        if booking_ref is None:
            return None
        booking = await self._stays.find_booking(normalise_ref(booking_ref))
        if booking is None:
            raise RestoreError(NO_BOOKING)
        return booking

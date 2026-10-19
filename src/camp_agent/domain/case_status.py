from dataclasses import dataclass, replace
from datetime import datetime

from camp_agent.domain.case_state import CaseState, StateReason
from camp_agent.domain.urgency import Urgency, higher_urgency


@dataclass(frozen=True)
class CaseStatus:
    state: CaseState = CaseState.OPEN
    reason: StateReason | None = None
    safety: bool = False
    urgency: Urgency = Urgency.NORMAL
    clarify_rounds: int = 0
    held_at: datetime | None = None
    closed_at: datetime | None = None

    def emergency(self, now: datetime) -> "CaseStatus":
        return replace(
            self,
            state=CaseState.HELD,
            reason=StateReason.EMERGENCY,
            safety=True,
            urgency=Urgency.URGENT,
            held_at=self.held_at or now,
            closed_at=None,
        )

    def hold(self, reason: StateReason, now: datetime) -> "CaseStatus":
        # A parked case leaves parking only by a safety hit or a staff restore (I10).
        if self.state is not CaseState.OPEN:
            return self
        return replace(self, state=CaseState.HELD, reason=reason, held_at=now)

    def park(self, reason: StateReason) -> "CaseStatus":
        # Held work stays with staff, and a safety case is never parked (I9).
        if self.state is not CaseState.OPEN or self.safety:
            return self
        return replace(self, state=CaseState.PARKED, reason=reason)

    def park_unverified(self) -> "CaseStatus":
        # Failed verification parks held work too (I10); only a safety case stays held (I9).
        if self.safety:
            return self
        return replace(self, state=CaseState.PARKED, reason=StateReason.VERIFICATION, held_at=None)

    def clarify(self, max_rounds: int, now: datetime) -> "CaseStatus":
        if self.clarify_rounds >= max_rounds:
            return self.hold(StateReason.CLARIFY_LIMIT, now)
        return replace(self, clarify_rounds=self.clarify_rounds + 1)

    def understood(self) -> "CaseStatus":
        return replace(self, clarify_rounds=0)

    def restore(self, held: StateReason | None, now: datetime) -> "CaseStatus":
        # A staff restore ends the park (D33); work still held goes back to staff.
        if self.state is not CaseState.PARKED:
            return self
        if held is None:
            return replace(self, state=CaseState.OPEN, reason=None, held_at=None)
        return replace(self, state=CaseState.HELD, reason=held, held_at=now)

    def release(self) -> "CaseStatus":
        # Staff settled the hold; the clarify count starts again for the next message.
        if self.state is not CaseState.HELD:
            return self
        return replace(self, state=CaseState.OPEN, reason=None, held_at=None, clarify_rounds=0)

    def close(self, now: datetime) -> "CaseStatus":
        return replace(
            self,
            state=CaseState.CLOSED,
            reason=None,
            clarify_rounds=0,
            held_at=None,
            closed_at=now,
        )

    def reopen(self) -> "CaseStatus":
        if self.state is not CaseState.CLOSED:
            return self
        return replace(self, state=CaseState.OPEN, closed_at=None)

    def raise_urgency(self, urgency: Urgency) -> "CaseStatus":
        return replace(self, urgency=higher_urgency(self.urgency, urgency))

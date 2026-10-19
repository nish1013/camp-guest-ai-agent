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

    def emergency(self, now: datetime) -> "CaseStatus":
        return replace(
            self,
            state=CaseState.HELD,
            reason=StateReason.EMERGENCY,
            safety=True,
            urgency=Urgency.URGENT,
            held_at=self.held_at or now,
        )

    def hold(self, reason: StateReason, now: datetime) -> "CaseStatus":
        if self.state is CaseState.HELD:
            return self
        return replace(self, state=CaseState.HELD, reason=reason, held_at=now)

    def park(self, reason: StateReason) -> "CaseStatus":
        # Held work stays with staff, and a safety case is never parked (I9).
        if self.state is not CaseState.OPEN or self.safety:
            return self
        return replace(self, state=CaseState.PARKED, reason=reason)

    def clarify(self, max_rounds: int, now: datetime) -> "CaseStatus":
        if self.clarify_rounds >= max_rounds:
            return self.hold(StateReason.CLARIFY_LIMIT, now)
        return replace(self, clarify_rounds=self.clarify_rounds + 1)

    def understood(self) -> "CaseStatus":
        return replace(self, clarify_rounds=0)

    def raise_urgency(self, urgency: Urgency) -> "CaseStatus":
        return replace(self, urgency=higher_urgency(self.urgency, urgency))

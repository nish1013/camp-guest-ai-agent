from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class ScopeSource(StrEnum):
    QR = "qr"
    STEP_UP = "step_up"
    STAFF = "staff"


@dataclass(frozen=True)
class Scope:
    cabin: str
    stay_from: date
    stay_to: date
    source: ScopeSource

    def active_on(self, today: date) -> bool:
        return self.stay_from <= today <= self.stay_to

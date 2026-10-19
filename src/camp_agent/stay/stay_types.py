from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Booking:
    booking_ref: str
    surname: str
    cabin: str
    stay_from: date
    stay_to: date

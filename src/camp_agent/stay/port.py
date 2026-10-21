from dataclasses import dataclass
from datetime import date
from typing import Protocol


class StayError(Exception):
    pass


@dataclass(frozen=True)
class Booking:
    booking_ref: str
    surname: str
    cabin: str
    stay_from: date
    stay_to: date


class StayContextPort(Protocol):
    # booking_ref arrives normalised by normalise_ref. Adapters raise StayError when the booking
    # system cannot be reached.
    async def find_booking(self, booking_ref: str) -> Booking | None: ...

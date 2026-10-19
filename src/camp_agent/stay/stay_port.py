from typing import Protocol

from camp_agent.stay.stay_types import Booking


class StayContextPort(Protocol):
    # booking_ref arrives normalised by normalise_ref. Adapters raise StayError when the booking
    # system cannot be reached.
    async def find_booking(self, booking_ref: str) -> Booking | None: ...

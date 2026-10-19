from datetime import date, timedelta
from pathlib import Path

import anyio
from pydantic import BaseModel, TypeAdapter, ValidationError

from camp_agent.clock import Clock
from camp_agent.domain.step_up import normalise_ref
from camp_agent.stay.stay_error import StayError
from camp_agent.stay.stay_types import Booking


class SeedStay(BaseModel):
    booking_ref: str
    surname: str
    cabin: str
    from_day: int
    to_day: int


_SEEDS = TypeAdapter(list[SeedStay])


class SeedStays:
    def __init__(self, path: Path, clock: Clock) -> None:
        self._path = anyio.Path(path)
        self._clock = clock

    async def find_booking(self, booking_ref: str) -> Booking | None:
        for booking in await self._bookings():
            if normalise_ref(booking.booking_ref) == booking_ref:
                return booking
        return None

    async def _bookings(self) -> list[Booking]:
        try:
            text = await self._path.read_text(encoding="utf-8")
        except OSError as error:
            raise StayError(f"cannot read {self._path}") from error
        return parse_stays(text, self._clock.today())


# Seed days count from today, so the demo bookings stay current on any run date.
def parse_stays(text: str, today: date) -> list[Booking]:
    try:
        seeds = _SEEDS.validate_json(text)
    except ValidationError as error:
        raise StayError("seed stays are malformed") from error
    return [
        Booking(
            seed.booking_ref,
            seed.surname,
            seed.cabin,
            today + timedelta(days=seed.from_day),
            today + timedelta(days=seed.to_day),
        )
        for seed in seeds
    ]

from pathlib import Path

import anyio
from pydantic import TypeAdapter, ValidationError

from camp_agent.domain.step_up import normalise_ref
from camp_agent.stay.stay_error import StayError
from camp_agent.stay.stay_types import Booking

_SEEDS = TypeAdapter(list[Booking])


class SeedStays:
    def __init__(self, path: Path) -> None:
        self._path = anyio.Path(path)

    async def find_booking(self, booking_ref: str) -> Booking | None:
        for booking in await self._bookings():
            if normalise_ref(booking.booking_ref) == booking_ref:
                return booking
        return None

    async def _bookings(self) -> list[Booking]:
        try:
            return parse_stays(await self._path.read_text(encoding="utf-8"))
        except OSError as error:
            raise StayError(f"cannot read {self._path}") from error


def parse_stays(text: str) -> list[Booking]:
    try:
        return _SEEDS.validate_json(text)
    except ValidationError as error:
        raise StayError("seed stays are malformed") from error

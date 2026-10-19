from datetime import date, timedelta
from pathlib import Path

import pytest

from camp_agent.config import Settings
from camp_agent.stay.seed_stays import SeedStays, parse_stays
from camp_agent.stay.stay_error import StayError
from tests.fakes import FakeClock, oct_19

pytestmark = pytest.mark.anyio


async def test_us7_finds_seed_by_ref() -> None:
    booking = await SeedStays(Settings().stays_path, oct_19()).find_booking("BK48213")

    assert booking is not None
    assert (booking.surname, booking.cabin) == ("Müller", "C12")
    assert (booking.stay_from, booking.stay_to) == (date(2026, 10, 18), date(2026, 10, 25))


async def test_us7_unknown_ref_none() -> None:
    assert await SeedStays(Settings().stays_path, oct_19()).find_booking("BK00000") is None


async def test_d41_unreadable_raises(tmp_path: Path) -> None:
    with pytest.raises(StayError):
        await SeedStays(tmp_path / "missing.json", oct_19()).find_booking("BK48213")


def test_d41_malformed_raises() -> None:
    with pytest.raises(StayError):
        parse_stays('[{"booking_ref": "BK-1"}]', date(2026, 10, 19))


async def test_us7_seed_days_count_from_today() -> None:
    later = FakeClock(oct_19().now() + timedelta(days=30))
    booking = await SeedStays(Settings().stays_path, later).find_booking("BK48213")

    assert booking is not None
    assert (booking.stay_from, booking.stay_to) == (date(2026, 11, 17), date(2026, 11, 24))

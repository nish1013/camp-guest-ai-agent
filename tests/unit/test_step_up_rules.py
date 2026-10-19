from datetime import date

import pytest

from camp_agent.domain.step_up import BookingCheck, check_booking, limit_reached, normalise_ref
from camp_agent.stay.stay_types import Booking

MULLER = Booking("BK-48213", "Müller", "C12", date(2026, 10, 18), date(2026, 10, 25))
TODAY = date(2026, 10, 19)


@pytest.mark.parametrize(
    "typed, expected",
    [
        ("BK-48213", "BK48213"),
        ("BK 48213", "BK48213"),
        (" BK48213 ", "BK48213"),
        ("BK - 482 13", "BK48213"),
        ("bk-48213", "bk48213"),
    ],
)
def test_d2_ref_drops_separators(typed: str, expected: str) -> None:
    assert normalise_ref(typed) == expected


@pytest.mark.parametrize(
    "surname, hint, today, expected",
    [
        ("  muller ", None, TODAY, BookingCheck.MATCHED),
        ("MÜLLER", None, TODAY, BookingCheck.MATCHED),
        ("Müller", "c12 ", TODAY, BookingCheck.MATCHED),
        ("Müller", "", TODAY, BookingCheck.MATCHED),
        ("Mueller", None, TODAY, BookingCheck.WRONG_SURNAME),
        ("Mull", None, TODAY, BookingCheck.WRONG_SURNAME),
        ("Müller", "C14", TODAY, BookingCheck.CABIN_DIFFERS),
        ("Müller", None, date(2026, 10, 18), BookingCheck.MATCHED),
        ("Müller", None, date(2026, 10, 25), BookingCheck.MATCHED),
        ("Müller", None, date(2026, 10, 17), BookingCheck.STAY_INACTIVE),
        ("Müller", None, date(2026, 10, 26), BookingCheck.STAY_INACTIVE),
    ],
)
def test_us7_booking_check(
    surname: str, hint: str | None, today: date, expected: BookingCheck
) -> None:
    assert check_booking(MULLER, surname, hint, today) is expected


def test_us7_no_booking() -> None:
    assert check_booking(None, "Müller", None, TODAY) is BookingCheck.NO_BOOKING


@pytest.mark.parametrize("failures, reached", [(2, False), (3, True), (4, True)])
def test_i10_limit_at_three(failures: int, reached: bool) -> None:
    assert limit_reached(failures, 3) is reached

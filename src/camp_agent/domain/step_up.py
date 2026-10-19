import re
import unicodedata
from datetime import date
from enum import StrEnum

from camp_agent.domain.scope import Scope, ScopeSource
from camp_agent.stay.stay_types import Booking

_REF_SEPARATORS = re.compile(r"[\s-]+")


class BookingCheck(StrEnum):
    MATCHED = "matched"
    NO_BOOKING = "no_booking"
    WRONG_SURNAME = "wrong_surname"
    CABIN_DIFFERS = "cabin_differs"
    STAY_INACTIVE = "stay_inactive"


def normalise_ref(ref: str) -> str:
    # A hyphen is formatting like a space: "BK 48213" is the booking BK-48213 (US7).
    return _REF_SEPARATORS.sub("", ref)


def normalise_surname(surname: str) -> str:
    decomposed = unicodedata.normalize("NFKD", surname.casefold())
    letters = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(letters.split())


def normalise_cabin(cabin: str) -> str:
    return cabin.strip().casefold()


def check_booking(
    booking: Booking | None, surname: str, cabin_hint: str | None, today: date
) -> BookingCheck:
    if booking is None:
        return BookingCheck.NO_BOOKING
    if normalise_surname(booking.surname) != normalise_surname(surname):
        return BookingCheck.WRONG_SURNAME
    if cabin_hint and normalise_cabin(cabin_hint) != normalise_cabin(booking.cabin):
        return BookingCheck.CABIN_DIFFERS
    if not booking.stay_from <= today <= booking.stay_to:
        return BookingCheck.STAY_INACTIVE
    return BookingCheck.MATCHED


def limit_reached(failures: int, limit: int) -> bool:
    return failures >= limit


def step_up_scope(booking: Booking) -> Scope:
    return Scope(booking.cabin, booking.stay_from, booking.stay_to, ScopeSource.STEP_UP)

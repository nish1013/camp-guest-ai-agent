from datetime import date, datetime, time

import pytest

from camp_agent.domain.arg_validation import ValidationOutcome, check_table_args
from camp_agent.domain.guest_status import table_line
from camp_agent.domain.route_guard import TaskState
from camp_agent.domain.table_flow import TableBooking, TableTask, next_to_book
from tests.fakes import CAMP_TZ
from tests.unit.triage_support import C12

NOW = datetime(2026, 10, 19, 14, 0, tzinfo=CAMP_TZ)
OCT_19 = date(2026, 10, 19)
DINNER = time(19, 30)
PARTY = "party must be 1 to 12"
STAY = "date must be from 2026-10-18 to 2026-10-25"


@pytest.mark.parametrize(
    "tool, cabin, party, day, at, reasons",
    [
        ("request_table", "C12", 4, OCT_19, DINNER, ()),
        ("request_table", "C14", 4, OCT_19, DINNER, ("cabin must be C12",)),
        ("create_ticket", "C12", 4, OCT_19, DINNER, ("tool must be request_table",)),
        ("request_table", "C12", 0, OCT_19, DINNER, (PARTY,)),
        ("request_table", "C12", 1, OCT_19, DINNER, ()),
        ("request_table", "C12", 12, OCT_19, DINNER, ()),
        ("request_table", "C12", 13, OCT_19, DINNER, (PARTY,)),
        ("request_table", "C12", None, OCT_19, DINNER, (PARTY,)),
        ("request_table", "C12", 4, None, DINNER, ("date and time must be given",)),
        ("request_table", "C12", 4, OCT_19, None, ("date and time must be given",)),
        ("request_table", "C12", 4, date(2026, 10, 17), DINNER, (STAY,)),
        ("request_table", "C12", 4, date(2026, 10, 18), DINNER, ("time must be later than now",)),
        ("request_table", "C12", 4, date(2026, 10, 25), DINNER, ()),
        ("request_table", "C12", 4, date(2026, 10, 26), DINNER, (STAY,)),
        ("request_table", "C12", 4, OCT_19, time(14, 0), ("time must be later than now",)),
        ("request_table", "C12", 4, OCT_19, time(14, 1), ()),
    ],
    ids=[
        "pass",
        "other-cabin",
        "other-tool",
        "party-0",
        "party-1",
        "party-12",
        "party-13",
        "no-party",
        "no-date",
        "no-time",
        "before-stay",
        "arrival-day-past",
        "last-day",
        "after-stay",
        "now",
        "one-minute-on",
    ],
)
def test_d15_table_args(
    tool: str,
    cabin: str,
    party: int | None,
    day: date | None,
    at: time | None,
    reasons: tuple[str, ...],
) -> None:
    check = check_table_args(tool, cabin, party, day, at, C12, NOW)

    assert check.reasons == reasons
    assert (check.outcome is ValidationOutcome.PASS) is (reasons == ())
    assert (check.booking is not None) is (reasons == ())


def test_d15_table_args_never_rewritten() -> None:
    check = check_table_args("request_table", "C12", 4, OCT_19, DINNER, C12, NOW)

    assert check.booking == TableBooking("C12", 4, OCT_19, DINNER)


def test_us5_table_line() -> None:
    assert table_line(4, OCT_19, DINNER) == "Table for 4 at 19:30 on 19 Oct"


def test_us5_next_to_book_skips_settled() -> None:
    tables = [
        TableTask("m1/t0", TaskState.BOOKING_REQUESTED, "a"),
        TableTask("m1/t1", TaskState.AWAITING_SCOPE, "b"),
        TableTask("m1/t2", TaskState.HELD, "c"),
        TableTask("m2/t0", TaskState.QUEUED, "d"),
    ]

    assert next_to_book(tables) == tables[3]
    assert next_to_book(tables[:3]) is None

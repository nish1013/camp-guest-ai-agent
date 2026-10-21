from datetime import UTC, datetime, time, timedelta

import pytest

from camp_agent.domain.cases import DeskHours, is_overdue, queue_rank
from camp_agent.domain.routing import Urgency
from tests.fakes import CAMP_TZ

DESK = DeskHours(time(8), time(22), CAMP_TZ)
GATE = timedelta(minutes=15)


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=CAMP_TZ).astimezone(UTC)


@pytest.mark.parametrize(
    ("held", "now", "overdue"),
    [
        (at(19, 14), at(19, 14, 14), False),
        (at(19, 14), at(19, 14, 15), True),
        (at(19, 14), at(19, 14, 16), True),
        (at(19, 23, 10), at(20, 7, 59), False),
        (at(19, 23, 10), at(20, 8, 14), False),
        (at(19, 23, 10), at(20, 8, 15), True),
        (at(19, 21, 50), at(20, 8, 4), False),
        (at(19, 21, 50), at(20, 8, 5), True),
    ],
    ids=[
        "14:14",
        "14:15",
        "14:16",
        "night-07:59",
        "night-08:14",
        "night-08:15",
        "close-4",
        "close-5",
    ],
)
def test_d30_overdue_counts_desk_time(held: datetime, now: datetime, overdue: bool) -> None:
    assert is_overdue(held, now, DESK, GATE) is overdue


def test_d11_not_held_never_overdue() -> None:
    assert not is_overdue(None, at(19, 20), DESK, GATE)


def test_d30_desk_must_open_first() -> None:
    with pytest.raises(ValueError, match="open before"):
        DeskHours(time(22), time(8), CAMP_TZ)


def test_d8_urgent_first_then_oldest() -> None:
    cases = {
        "can_wait": queue_rank(Urgency.CAN_WAIT, False, at(19, 9)),
        "normal_new": queue_rank(Urgency.NORMAL, False, at(19, 12)),
        "normal_old": queue_rank(Urgency.NORMAL, False, at(19, 10)),
        "urgent": queue_rank(Urgency.URGENT, False, at(19, 13)),
    }

    assert sorted(cases, key=cases.__getitem__) == [
        "urgent",
        "normal_old",
        "normal_new",
        "can_wait",
    ]


def test_d11_overdue_first_within_urgency() -> None:
    cases = {
        "normal_old": queue_rank(Urgency.NORMAL, False, at(19, 10)),
        "normal_overdue": queue_rank(Urgency.NORMAL, True, at(19, 12)),
        "urgent": queue_rank(Urgency.URGENT, False, at(19, 13)),
    }

    assert sorted(cases, key=cases.__getitem__) == ["urgent", "normal_overdue", "normal_old"]

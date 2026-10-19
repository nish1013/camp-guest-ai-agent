from datetime import UTC, datetime, time
from pathlib import Path

import pytest

from camp_agent.domain.case_state import CaseState, StateReason
from camp_agent.domain.case_status import CaseStatus
from camp_agent.domain.desk_hours import DeskHours
from camp_agent.domain.guest_status import (
    CLARIFY,
    CLOSED,
    NOT_VERIFIED,
    RECEIVED,
    WAITING_ON_RECEPTION,
    WITH_RECEPTION,
    booking_status,
    guest_status,
    ticket_status,
)
from camp_agent.domain.route_guard import TaskState
from camp_agent.domain.specialist import Team
from camp_agent.domain.ticket_status import TicketStatus
from tests.fakes import CAMP_TZ

DESK = DeskHours(time(8), time(22), CAMP_TZ)
GUIDANCE = "Leave the cabin. Call 999."
RECEPTION = "Call reception on 01632 960123."
OPENS = "Reception opens at 08:00."
T0 = datetime(2026, 10, 19, 13, tzinfo=UTC)
PAGE = Path("src/camp_agent/http/templates/index.html").read_text(encoding="utf-8")


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, 19, hour, minute, tzinfo=CAMP_TZ)


def held(reason: StateReason) -> CaseStatus:
    return CaseStatus().hold(reason, T0)


def status_at(status: CaseStatus, now: datetime) -> str:
    opens = None if DESK.is_open(now) else DESK.opens
    return guest_status(status, GUIDANCE, RECEPTION, opens)


@pytest.mark.parametrize(
    ("now", "open_"),
    [(at(7, 59), False), (at(8), True), (at(21, 59), True), (at(22), False), (at(23, 10), False)],
    ids=["07:59", "08:00", "21:59", "22:00", "23:10"],
)
def test_d30_desk_open(now: datetime, open_: bool) -> None:
    assert DESK.is_open(now) is open_


@pytest.mark.parametrize(
    ("status", "text"),
    [
        (CaseStatus(), RECEIVED),
        (CaseStatus(clarify_rounds=1), CLARIFY),
        (held(StateReason.MONEY), WAITING_ON_RECEPTION),
        (held(StateReason.CLARIFY_LIMIT), WAITING_ON_RECEPTION),
        (held(StateReason.FAULT_REVIEW), WAITING_ON_RECEPTION),
        (held(StateReason.BOOKING_REVIEW), WAITING_ON_RECEPTION),
        (held(StateReason.LLM_FAILED), WITH_RECEPTION),
        (held(StateReason.TICKETING_DOWN), WITH_RECEPTION),
        (CaseStatus().emergency(T0), GUIDANCE),
        (CaseStatus().park(StateReason.SPAM), RECEIVED),
        (CaseStatus().park_unverified(), f"{NOT_VERIFIED} {RECEPTION}"),
        (CaseStatus().close(T0), CLOSED),
    ],
    ids=[
        "open",
        "clarify",
        "money",
        "clarify-limit",
        "fault-review",
        "booking-review",
        "llm-failed",
        "ticketing-down",
        "emergency",
        "spam-park",
        "verification-park",
        "closed",
    ],
)
def test_us9_status_from_template(status: CaseStatus, text: str) -> None:
    assert status_at(status, at(14)) == text


def test_us9_every_state_has_text() -> None:
    for state in CaseState:
        for reason in [None, *StateReason]:
            status = CaseStatus(state=state, reason=reason)
            assert status_at(status, at(14)).strip()
            assert status_at(status, at(23, 10)).strip()


@pytest.mark.parametrize(
    "reason", [r for r in StateReason if r not in {StateReason.EMERGENCY, StateReason.SPAM}]
)
def test_d30_held_at_night_names_opening(reason: StateReason) -> None:
    status = CaseStatus().hold(reason, at(23, 10))

    assert status_at(status, at(23, 10)) == OPENS
    assert status_at(status, at(8)) != OPENS


def test_d8_emergency_at_night_shows_guidance() -> None:
    assert status_at(CaseStatus().emergency(at(23, 10)), at(23, 10)) == GUIDANCE


def test_d30_only_held_names_opening() -> None:
    assert status_at(CaseStatus(), at(23, 10)) == RECEIVED
    assert status_at(CaseStatus().close(T0), at(23, 10)) == CLOSED


@pytest.mark.parametrize(
    ("team", "status", "text"),
    [
        (Team.MAINTENANCE, TicketStatus.OPEN, "Logged with maintenance"),
        (Team.MAINTENANCE, TicketStatus.IN_PROGRESS, "Maintenance is working on it"),
        (Team.HOUSEKEEPING, TicketStatus.OPEN, "Logged with housekeeping"),
        (Team.HOUSEKEEPING, TicketStatus.IN_PROGRESS, "Housekeeping is working on it"),
        (Team.MAINTENANCE, TicketStatus.DONE, "Done"),
        (Team.HOUSEKEEPING, TicketStatus.CANCELLED, "Cancelled"),
    ],
)
def test_us9_ticket_line(team: Team, status: TicketStatus, text: str) -> None:
    assert ticket_status(team, status) == text


@pytest.mark.parametrize(
    ("state", "text"),
    [
        (TaskState.BOOKING_REQUESTED, "Waiting for the restaurant to confirm"),
        (TaskState.BOOKING_CONFIRMED, "Booked: table for 4 at 19:30."),
        (TaskState.BOOKING_DECLINED, "The restaurant could not take this booking."),
    ],
)
def test_us9_booking_line(state: TaskState, text: str) -> None:
    assert booking_status(state, 4, time(19, 30)) == text


@pytest.mark.parametrize(
    "rule",
    [
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "max-width: 40rem",
        "overflow-wrap: anywhere",
        "box-sizing: border-box",
        "min-width: 0",
        "font-size: 1rem",
    ],
    ids=["viewport", "max-width", "wrap", "box-sizing", "fieldset", "no-ios-zoom"],
)
def test_us9_page_fits_375px(rule: str) -> None:
    assert rule in PAGE
    assert "user-scalable" not in PAGE

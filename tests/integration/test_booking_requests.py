from datetime import date, time, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from camp_agent.domain.route_guard import Category, Route
from camp_agent.domain.urgency import Urgency
from camp_agent.llm.llm_types import Classification, GuideAnswer
from camp_agent.qr.qr_token import QrTokens
from tests.fakes import FakeClock, FakeLlm, table_args
from tests.integration.intake_support import SECRET, audit, rows, send

C12 = QrTokens(SECRET).issue("C12", date(2026, 10, 18), date(2026, 10, 25))
TABLE = "table for 4 at 19:30 tonight"
IS_IT_BOOKED = "is it booked?"
POOL = "When does the pool open?"
DINNER = Classification(category=Category.RESTAURANT, route=Route.TABLE, urgency=Urgency.NORMAL)
REFUND = "I want a refund for last night"
MONEY = Classification(category=Category.REFUND, route=Route.MONEY, urgency=Urgency.NORMAL)
LINE = "<em>Table for 4 at 19:30 on 19 Oct</em>: Waiting for the restaurant to confirm"
PHONE = "Call 01632 960124 to ask about a table."
FORM = 'id="step-up-form"'
UNCHECKED_BOOKINGS = (
    "SELECT count(*) FROM tasks t WHERE t.booking_party IS NOT NULL AND NOT EXISTS ("
    " SELECT 1 FROM validation_records v WHERE v.case_id = t.case_id"
    " AND v.step_id = t.step_id AND v.outcome = 'pass')"
)


@pytest.fixture
def llm() -> FakeLlm:
    # An answer that claims a booking: only the follow-up rule keeps it off the page.
    claims = GuideAnswer(text="Yes, your table is Booked.", section_id="restaurant")
    return FakeLlm(
        classes={TABLE: DINNER, REFUND: MONEY},
        answers={IS_IT_BOOKED: claims, TABLE: GuideAnswer(text=PHONE, section_id="restaurant")},
    )


def bookings(db: Engine) -> list[tuple[object, ...]]:
    return rows(
        db,
        "SELECT kind, state, cabin, booking_party, booking_date, booking_time FROM tasks"
        " ORDER BY id",
    )


def test_us5_table_waits_for_restaurant(triage_client: TestClient, db: Engine) -> None:
    triage_client.get(f"/q/{C12}")
    send(triage_client, TABLE)

    page = triage_client.get("/").text
    assert bookings(db) == [
        ("table", "booking_requested", "C12", 4, date(2026, 10, 19), time(19, 30))
    ]
    assert LINE in page
    assert "Booked" not in page
    assert rows(db, UNCHECKED_BOOKINGS) == [(0,)]
    assert audit(db)[-1] == ("booking", "requested")


def test_us5_is_it_booked_unchanged(triage_client: TestClient, db: Engine, llm: FakeLlm) -> None:
    triage_client.get(f"/q/{C12}")
    send(triage_client, TABLE)
    calls = len(llm.calls)

    send(triage_client, IS_IT_BOOKED)

    page = triage_client.get("/").text
    assert len(llm.calls) == calls
    assert LINE in page
    assert "Booked" not in page and "booked." not in page
    assert bookings(db)[0][1] == "booking_requested"
    assert audit(db)[-1] == ("safety", "joined")


def test_us5_no_scope_step_up_then_request(triage_client: TestClient, db: Engine) -> None:
    token: str = send(triage_client, TABLE).cookies["case_token"]

    assert FORM in triage_client.get("/").text
    assert bookings(db)[0][:2] == ("table", "awaiting_scope")

    triage_client.post(f"/c/{token}/step-up", data={"surname": "Müller", "booking_ref": "BK-48213"})

    assert bookings(db)[0][:3] == ("table", "booking_requested", "C12")
    assert LINE in triage_client.get("/").text


def test_d19_stay_ended_guide_answer(
    triage_client: TestClient, db: Engine, clock: FakeClock, llm: FakeLlm
) -> None:
    # A held refund keeps the case open past its stay; an answered question would close it.
    triage_client.get(f"/q/{C12}")
    send(triage_client, REFUND)
    clock.advance(timedelta(days=7))

    send(triage_client, TABLE)

    page = triage_client.get("/").text
    assert PHONE in page
    assert "draft_table" not in llm.calls
    assert rows(db, "SELECT kind, state, booking_party FROM tasks ORDER BY id")[-1] == (
        "question",
        "done",
        None,
    )


@pytest.mark.parametrize(
    "llm",
    [FakeLlm(classes={TABLE: DINNER}, tables={TABLE: [table_args(party=None)] * 2})],
    ids=["no-party"],
)
def test_i6_blocked_table_held(triage_client: TestClient, db: Engine) -> None:
    triage_client.get(f"/q/{C12}")
    send(triage_client, TABLE)

    assert bookings(db) == [("table", "held", None, None, None, None)]
    assert rows(db, "SELECT state, state_reason FROM cases") == [("held", "booking_review")]
    assert rows(db, "SELECT outcome FROM validation_records") == [("block",), ("block",)]
    assert "Waiting on reception" in triage_client.get("/").text

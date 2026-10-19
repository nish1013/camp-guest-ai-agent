import logging
from datetime import date, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from markupsafe import escape
from sqlalchemy import Engine

from camp_agent.domain.guest_status import (
    BOOKING_FOUND,
    BOOKINGS_DOWN,
    NO_BOOKING_MATCH,
    NOT_VERIFIED,
)
from camp_agent.domain.route_guard import Category, Route
from camp_agent.domain.urgency import Urgency
from camp_agent.llm.llm_types import Classification
from camp_agent.qr.qr_token import QrTokens
from tests.fakes import FakeClock, FakeLlm, SwitchableStays, demo_section
from tests.integration.intake_support import SECRET, audit, count, rows

FAULT = "no hot water"
HOT_WATER = Classification(category=Category.MAINTENANCE, route=Route.FAULT, urgency=Urgency.URGENT)
C12 = QrTokens(SECRET).issue("C12", date(2026, 10, 18), date(2026, 10, 25))
RECEPTION = demo_section("reception").body
FORM = 'id="step-up-form"'


@pytest.fixture
def llm() -> FakeLlm:
    return FakeLlm(classes={FAULT: HOT_WATER})


def report(client: TestClient, text: str = FAULT, cabin_hint: str = "") -> str:
    data = {"text": text, "idempotency_key": str(uuid4()), "cabin_hint": cabin_hint}
    token: str = client.post("/messages", data=data).cookies["case_token"]
    return token


def step_up(client: TestClient, token: str, surname: str, ref: str) -> Response:
    return client.post(f"/c/{token}/step-up", data={"surname": surname, "booking_ref": ref})


def case_row(db: Engine) -> tuple[object, ...]:
    return rows(db, "SELECT state, state_reason, scope_cabin, scope_source FROM cases")[0]


def task_states(db: Engine) -> list[tuple[object, ...]]:
    return rows(db, "SELECT kind, state FROM tasks ORDER BY id")


def test_us7_fault_without_scope_asks(triage_client: TestClient, db: Engine) -> None:
    report(triage_client)

    assert FORM in triage_client.get("/").text
    assert task_states(db) == [("fault", "awaiting_scope")]


def test_us7_qr_scope_no_form(triage_client: TestClient, db: Engine) -> None:
    triage_client.get(f"/q/{C12}")
    report(triage_client)

    assert FORM not in triage_client.get("/").text
    assert task_states(db) == [("fault", "ticketed")]


def test_us7_question_needs_no_form(triage_client: TestClient) -> None:
    report(triage_client, "When does the pool open?")

    assert FORM not in triage_client.get("/").text


def test_us7_match_sets_scope_and_resumes(triage_client: TestClient, db: Engine) -> None:
    token = report(triage_client)

    response = step_up(triage_client, token, "  muller ", "BK 48213")

    assert response.status_code == 200
    assert BOOKING_FOUND in response.text
    assert FORM not in response.text
    assert case_row(db) == ("open", None, "C12", "step_up")
    assert rows(db, "SELECT scope_stay_from, scope_stay_to FROM cases") == [
        (date(2026, 10, 18), date(2026, 10, 25))
    ]
    assert task_states(db) == [("fault", "ticketed")]
    assert audit(db)[-4:] == [
        ("step_up", "matched"),
        ("route_guard", "fault"),
        ("same", "none"),
        ("ticket", "created"),
    ]


@pytest.mark.parametrize(
    "surname, ref",
    [("Müller", "BK-99999"), ("Jones", "BK-48213"), ("Jones", "BK-39950")],
    ids=["wrong-ref", "wrong-surname", "stay-ended"],
)
def test_us7_no_match_fixed_reply(
    triage_client: TestClient, db: Engine, surname: str, ref: str
) -> None:
    token = report(triage_client)

    response = step_up(triage_client, token, surname, ref)

    assert response.status_code == 200
    assert NO_BOOKING_MATCH in response.text
    assert FORM in response.text
    assert case_row(db) == ("open", None, None, None)
    assert task_states(db) == [("fault", "awaiting_scope")]


def test_us7_cabin_differs_same_reply(triage_client: TestClient, db: Engine) -> None:
    token = report(triage_client, cabin_hint="C12")

    wrong_ref = step_up(triage_client, token, "Okafor", "BK-99999")
    other_cabin = step_up(triage_client, token, "Okafor", "BK-51107")

    assert other_cabin.status_code == wrong_ref.status_code == 200
    assert other_cabin.text == wrong_ref.text
    assert "C14" not in other_cabin.text
    assert case_row(db) == ("open", None, None, None)


def test_i10_third_fail_parks_fourth_stays(
    triage_client: TestClient, db: Engine, stays: SwitchableStays
) -> None:
    token = report(triage_client)
    replies = [step_up(triage_client, token, "Müller", "BK-99999") for _ in range(3)]

    assert [NO_BOOKING_MATCH in r.text for r in replies] == [True, True, False]
    assert escape(f"{NOT_VERIFIED} {RECEPTION}") in replies[2].text
    assert FORM not in replies[2].text
    assert case_row(db)[:2] == ("parked", "verification")

    fourth = step_up(triage_client, token, "Müller", "BK-48213")

    assert stays.lookups == 3
    assert case_row(db) == ("parked", "verification", None, None)
    assert escape(f"{NOT_VERIFIED} {RECEPTION}") in fourth.text
    assert count(db, "verification_attempts") == 3
    assert [s for s in audit(db) if s[0] == "step_up"] == [
        ("step_up", "failed"),
        ("step_up", "failed"),
        ("step_up", "parked"),
    ]


def test_us7_ip_limit_parks_other_case(
    triage_client: TestClient, db: Engine, stays: SwitchableStays, clock: FakeClock
) -> None:
    first = report(triage_client)
    for _ in range(3):
        step_up(triage_client, first, "Müller", "BK-99999")
    triage_client.cookies.clear()
    second = report(triage_client)

    step_up(triage_client, second, "Müller", "BK-48213")

    assert stays.lookups == 3
    assert rows(db, "SELECT state, state_reason FROM cases ORDER BY id") == [
        ("parked", "verification"),
        ("parked", "verification"),
    ]


def test_us7_ip_limit_ends_after_hour(
    triage_client: TestClient, db: Engine, clock: FakeClock
) -> None:
    first = report(triage_client)
    for _ in range(3):
        step_up(triage_client, first, "Müller", "BK-99999")
    triage_client.cookies.clear()
    second = report(triage_client)
    clock.advance(timedelta(hours=1))

    response = step_up(triage_client, second, "Müller", "BK-48213")

    assert BOOKING_FOUND in response.text
    assert rows(db, "SELECT state, scope_source FROM cases ORDER BY id") == [
        ("parked", None),
        ("open", "step_up"),
    ]


def test_d41_stays_down_not_counted(
    triage_client: TestClient, db: Engine, stays: SwitchableStays
) -> None:
    token = report(triage_client)
    stays.down = True

    replies = [step_up(triage_client, token, "Müller", "BK-48213") for _ in range(4)]

    assert all(escape(f"{BOOKINGS_DOWN} {RECEPTION}") in r.text for r in replies)
    assert count(db, "verification_attempts") == 0
    assert case_row(db) == ("open", None, None, None)
    stays.down = False
    assert BOOKING_FOUND in step_up(triage_client, token, "Müller", "BK-48213").text


def test_d3_form_fields_reach_no_llm_or_audit(
    triage_client: TestClient, db: Engine, llm: FakeLlm, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        token = report(triage_client)
        step_up(triage_client, token, "Okafor", "BK-77777")
        step_up(triage_client, token, "Müller", "BK 48213")
        report(triage_client, "When does the pool open?")

    stored = " ".join(
        str(row)
        for table in ("audit_entries", "verification_attempts", "messages", "tasks", "cases")
        for row in rows(db, f"SELECT * FROM {table}")
    )
    assert llm.calls.count("verify") == 1
    for secret in ("Müller", "muller", "Okafor", "48213", "77777"):
        assert all(secret not in sent for sent in llm.inputs), secret
        assert secret not in stored, secret
        assert secret not in caplog.text, secret


@pytest.mark.parametrize("token", ["unknown", "x" * 43])
def test_us7_unknown_case_404(triage_client: TestClient, token: str) -> None:
    report(triage_client)

    response = step_up(triage_client, token, "Müller", "BK-48213")

    assert response.status_code == 404


@pytest.mark.parametrize(
    "data",
    [{"surname": "Müller"}, {"surname": "  ", "booking_ref": "BK-48213"}],
    ids=["no-ref", "blank-surname"],
)
def test_us7_malformed_form_422(triage_client: TestClient, data: dict[str, str]) -> None:
    token = report(triage_client)

    assert triage_client.post(f"/c/{token}/step-up", data=data).status_code == 422


def test_i9_safety_case_locked_not_parked(
    triage_client: TestClient, db: Engine, stays: SwitchableStays, clock: FakeClock
) -> None:
    token = report(triage_client, "smoke coming from the heater")
    report(triage_client)
    for _ in range(3):
        step_up(triage_client, token, "Müller", "BK-99999")
    clock.advance(timedelta(hours=1))

    fourth = step_up(triage_client, token, "Müller", "BK-48213")

    assert stays.lookups == 3
    assert case_row(db) == ("held", "emergency", None, None)
    assert FORM not in fourth.text

from datetime import date
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import Engine

from camp_agent.domain.fault_type import FaultType
from camp_agent.domain.route_guard import Category, Route
from camp_agent.domain.urgency import Urgency
from camp_agent.llm.llm_types import Classification, Verdict
from camp_agent.qr.qr_token import QrTokens
from tests.fakes import FakeLlm, demo_section
from tests.integration.intake_support import SECRET, audit, count, rows, send

C12 = QrTokens(SECRET).issue("C12", date(2026, 10, 18), date(2026, 10, 25))
HOT_WATER = Classification(
    category=Category.MAINTENANCE,
    route=Route.FAULT,
    urgency=Urgency.URGENT,
    fault_type=FaultType.HOT_WATER,
)
HEATING = Classification(
    category=Category.MAINTENANCE,
    route=Route.FAULT,
    urgency=Urgency.NORMAL,
    fault_type=FaultType.HEATING,
)
TOWELS = Classification(
    category=Category.HOUSEKEEPING,
    route=Route.FAULT,
    urgency=Urgency.CAN_WAIT,
    fault_type=FaultType.SUPPLIES,
)
TWO = "heater is off and the tap leaks"
SPLIT_ASKED = "I found 2 issues: heater is off, the tap leaks. Correct?"
SAME_ASKED = "Same problem as the 14:00 heating report?"
CLASSES = {
    "no hot water": HOT_WATER,
    "extra towels": TOWELS,
    "heater broken": HEATING,
    "lounge heater broken": HEATING,
    "heater is off": HEATING,
    "the tap leaks": HEATING,
}
SAME_LLM = FakeLlm(classes=CLASSES, same={"heater broken": 1})
UNCHECKED_TICKETS = (
    "SELECT count(*) FROM tasks t WHERE t.ticket_ref IS NOT NULL AND NOT EXISTS ("
    " SELECT 1 FROM validation_records v WHERE v.case_id = t.case_id"
    " AND v.step_id = t.step_id AND v.outcome = 'pass')"
)


@pytest.fixture
def llm() -> FakeLlm:
    return FakeLlm(classes=CLASSES, splits={TWO: ["heater is off", "the tap leaks"]})


def guest(client: TestClient, text: str) -> str:
    client.cookies.clear()
    client.get(f"/q/{C12}")
    token: str = send(client, text).cookies["case_token"]
    return token


def reply(client: TestClient, token: str, confirmation: str, subject: str, yes: bool) -> Response:
    data = {"confirmation": confirmation, "subject": subject, "answer": "yes" if yes else "no"}
    return client.post(f"/c/{token}/answer", data=data)


def tickets(db: Engine) -> list[tuple[object, ...]]:
    return rows(db, "SELECT cabin, team, urgency, fault_type FROM demo_tickets ORDER BY id")


def task_tickets(db: Engine) -> list[tuple[object, ...]]:
    return rows(db, "SELECT state, ticket_ref FROM tasks ORDER BY id")


def test_us4_hot_water_logged(triage_client: TestClient, db: Engine) -> None:
    guest(triage_client, "no hot water")

    assert tickets(db) == [("C12", "maintenance", "urgent", "hot_water")]
    assert task_tickets(db) == [("ticketed", "T1")]
    assert "Logged with maintenance" in triage_client.get("/").text
    assert rows(db, UNCHECKED_TICKETS) == [(0,)]


def test_us4_towels_to_housekeeping(triage_client: TestClient, db: Engine) -> None:
    guest(triage_client, "extra towels")

    assert tickets(db) == [("C12", "housekeeping", "can_wait", "supplies")]
    assert "Logged with housekeeping" in triage_client.get("/").text


def test_d39_split_yes_two_tickets(triage_client: TestClient, db: Engine) -> None:
    token = guest(triage_client, TWO)

    assert SPLIT_ASKED in triage_client.get("/").text
    assert count(db, "demo_tickets") == 0

    response = reply(triage_client, token, "split", "m1", yes=True)

    assert response.status_code == 200
    assert task_tickets(db) == [("ticketed", "T1"), ("ticketed", "T2")]
    assert SPLIT_ASKED not in triage_client.get("/").text


def test_d39_split_no_held(triage_client: TestClient, db: Engine) -> None:
    token = guest(triage_client, TWO)

    response = reply(triage_client, token, "split", "m1", yes=False)

    assert "Waiting on reception" in response.text
    assert count(db, "demo_tickets") == 0
    assert rows(db, "SELECT state, state_reason FROM cases") == [("held", "fault_review")]
    assert task_tickets(db) == [("held", None), ("held", None)]


@pytest.mark.parametrize("llm", [SAME_LLM], ids=["same"])
def test_d38_same_yes_links(triage_client: TestClient, db: Engine) -> None:
    guest(triage_client, "lounge heater broken")
    second = guest(triage_client, "heater broken")

    assert SAME_ASKED in triage_client.get("/").text
    reply(triage_client, second, "same", "m2/t0", yes=True)

    assert count(db, "demo_tickets") == 1
    assert task_tickets(db) == [("ticketed", "T1"), ("ticketed", "T1")]
    assert rows(db, "SELECT checked_against FROM reports ORDER BY id") == [([],), ([1],)]
    assert rows(db, UNCHECKED_TICKETS) == [(0,)]


@pytest.mark.parametrize("llm", [SAME_LLM], ids=["same"])
def test_d38_same_no_new_ticket(triage_client: TestClient, db: Engine) -> None:
    guest(triage_client, "lounge heater broken")
    second = guest(triage_client, "heater broken")

    reply(triage_client, second, "same", "m2/t0", yes=False)

    assert task_tickets(db) == [("ticketed", "T1"), ("ticketed", "T2")]


def test_d38_different_no_question(triage_client: TestClient, db: Engine) -> None:
    guest(triage_client, "lounge heater broken")
    guest(triage_client, "heater broken")

    assert "Same problem" not in triage_client.get("/").text
    assert task_tickets(db) == [("ticketed", "T1"), ("ticketed", "T2")]


def test_d5_retried_key_one_ticket(triage_client: TestClient, db: Engine) -> None:
    triage_client.get(f"/q/{C12}")
    key = str(uuid4())

    send(triage_client, "no hot water", key)
    send(triage_client, "no hot water", key)

    assert count(db, "demo_tickets") == 1


def test_us4_stale_answer_changes_nothing(triage_client: TestClient, db: Engine) -> None:
    token = guest(triage_client, TWO)
    reply(triage_client, token, "split", "m1", yes=True)
    audited = count(db, "audit_entries")

    response = reply(triage_client, token, "split", "m1", yes=False)

    assert response.status_code == 200
    assert count(db, "audit_entries") == audited
    assert count(db, "demo_tickets") == 2


def test_us4_answer_unknown_case_404(triage_client: TestClient) -> None:
    guest(triage_client, TWO)

    assert reply(triage_client, "unknown", "split", "m1", yes=True).status_code == 404


@pytest.mark.parametrize(
    "data",
    [
        {"confirmation": "split", "subject": "m1", "answer": "maybe"},
        {"confirmation": "refund", "subject": "m1", "answer": "yes"},
        {"confirmation": "split", "subject": "m1%", "answer": "yes"},
    ],
    ids=["answer", "confirmation", "subject"],
)
def test_us4_malformed_answer_422(triage_client: TestClient, data: dict[str, str]) -> None:
    token = guest(triage_client, TWO)

    assert triage_client.post(f"/c/{token}/answer", data=data).status_code == 422


@pytest.mark.parametrize(
    "llm", [FakeLlm(classes=CLASSES, verdicts={"asdf!!!": Verdict.SPAM})], ids=["spam"]
)
def test_d14_follow_up_joins_case(triage_client: TestClient, db: Engine, llm: FakeLlm) -> None:
    guest(triage_client, "no hot water")
    calls = len(llm.calls)

    send(triage_client, "asdf!!!")

    assert len(llm.calls) == calls
    assert count(db, "messages") == 2
    assert rows(db, "SELECT state FROM cases") == [("open",)]
    assert task_tickets(db) == [("ticketed", "T1")]
    assert audit(db)[-1] == ("safety", "joined")


def test_d14_smoke_follow_up_emergency(triage_client: TestClient, db: Engine) -> None:
    guest(triage_client, "no hot water")

    send(triage_client, "now there is smoke")

    assert rows(db, "SELECT state, state_reason, safety, urgency FROM cases") == [
        ("held", "emergency", True, "urgent")
    ]
    assert demo_section("emergency").body in triage_client.get("/").text
    assert task_tickets(db)[0] == ("ticketed", "T1")

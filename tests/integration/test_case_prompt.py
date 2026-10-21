from datetime import date, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import Engine, text

from camp_agent.domain.faults import FaultType
from camp_agent.domain.routing import Category, Route, Urgency
from camp_agent.llm.port import Classification, Verdict
from camp_agent.qr.qr_token import QrTokens
from tests.fakes import FakeClock, FakeLlm, demo_section
from tests.integration.intake_support import SECRET, audit, rows, send

C12 = QrTokens(SECRET).issue("C12", date(2026, 10, 18), date(2026, 10, 25))
HOT_WATER = Classification(
    category=Category.MAINTENANCE,
    route=Route.FAULT,
    urgency=Urgency.URGENT,
    fault_type=FaultType.HOT_WATER,
)
IN_ACTION_LLM = FakeLlm(classes={"no hot water": HOT_WATER}, verdicts={"asdf!!!": Verdict.SPAM})
PROMPT = "Add to C12 or new request?"


def post(client: TestClient, message: str, **fields: str) -> Response:
    data = {"text": message, "idempotency_key": str(uuid4()), **fields}
    return client.post("/messages", data=data)


def add(client: TestClient, message: str, token: str) -> Response:
    return post(client, message, target="case", offered=token)


def messages_per_case(db: Engine) -> list[tuple[object, ...]]:
    return rows(db, "SELECT case_id, count(*) FROM messages GROUP BY case_id ORDER BY case_id")


def close_case(db: Engine, closed_at: str) -> None:
    with db.begin() as conn:
        conn.execute(text("UPDATE cases SET state = 'closed', closed_at = :at"), {"at": closed_at})


def test_d4_open_case_offered(client: TestClient) -> None:
    client.get(f"/q/{C12}")
    token = send(client, "where is the pool").cookies["case_token"]

    page = client.get("/").text

    assert PROMPT in page
    assert f'name="offered" value="{token}"' in page


def test_d4_offer_without_scope(client: TestClient) -> None:
    send(client, "where is the pool")

    assert "Add to your request or new request?" in client.get("/").text


def test_d4_offer_after_send(client: TestClient) -> None:
    client.get(f"/q/{C12}")

    assert PROMPT in send(client, "where is the pool").text


def test_d4_no_cookie_no_offer(client: TestClient) -> None:
    page = client.get("/").text

    assert "data-offer" not in page
    assert "data-picks" in page


def test_d4_closed_case_not_offered(client: TestClient, db: Engine) -> None:
    send(client, "where is the pool")
    close_case(db, "2026-10-19T13:00:00+00:00")

    page = client.get("/").text

    assert "data-offer" not in page
    assert "Closed" in page


def test_d4_new_request_opens_case(client: TestClient, db: Engine) -> None:
    first = send(client, "where is the pool").cookies["case_token"]

    second = post(client, "and towels please", target="new", pick="cleaning")

    assert second.cookies["case_token"] != first
    assert messages_per_case(db) == [(1, 1), (2, 1)]
    assert rows(db, "SELECT case_id, pick FROM messages ORDER BY id") == [
        (1, None),
        (2, "cleaning"),
    ]


def test_d4_add_joins_case(client: TestClient, db: Engine) -> None:
    token = send(client, "where is the pool").cookies["case_token"]

    joined = add(client, "also the heater is off", token)

    assert joined.cookies["case_token"] == token
    assert messages_per_case(db) == [(1, 2)]


def test_d4_add_drops_pick(client: TestClient, db: Engine) -> None:
    token = send(client, "where is the pool").cookies["case_token"]

    post(client, "also the heater", target="case", offered=token, pick="maintenance")

    assert rows(db, "SELECT pick FROM messages ORDER BY id") == [(None,), (None,)]


def test_d4_two_tabs_add_to_offered(client: TestClient, db: Engine) -> None:
    k1 = send(client, "where is the pool").cookies["case_token"]
    k2 = post(client, "towels please", target="new").cookies["case_token"]

    add(client, "also the heater is off", k1)

    assert k2 != k1
    assert messages_per_case(db) == [(1, 2), (2, 1)]


def test_d4_add_without_case_is_422(client: TestClient, db: Engine) -> None:
    send(client, "where is the pool")

    assert post(client, "more", target="case").status_code == 422
    assert post(client, "more", target="other").status_code == 422


def test_d20_closed_before_tap_reopens(client: TestClient, db: Engine) -> None:
    token = send(client, "where is the pool").cookies["case_token"]
    close_case(db, "2026-10-19T12:59:00+00:00")

    add(client, "one more thing", token)

    assert rows(db, "SELECT state FROM cases") == [("open",)]
    assert messages_per_case(db) == [(1, 2)]
    assert audit(db)[-1] == ("case", "reopened")


def test_d20_closed_long_ago_new_case(client: TestClient, db: Engine, clock: FakeClock) -> None:
    token = send(client, "where is the pool").cookies["case_token"]
    close_case(db, "2026-10-19T12:00:00+00:00")
    clock.advance(timedelta(hours=25))

    joined = add(client, "one more thing", token)

    assert joined.cookies["case_token"] != token
    assert messages_per_case(db) == [(1, 1), (2, 1)]


@pytest.mark.parametrize("llm", [IN_ACTION_LLM], ids=["in-action"])
def test_d4_add_runs_safety_only(triage_client: TestClient, db: Engine, llm: FakeLlm) -> None:
    triage_client.get(f"/q/{C12}")
    token = send(triage_client, "no hot water").cookies["case_token"]
    calls = len(llm.calls)

    add(triage_client, "asdf!!!", token)

    assert len(llm.calls) == calls
    assert rows(db, "SELECT state, ticket_ref FROM tasks") == [("ticketed", "T1")]
    assert rows(db, "SELECT state FROM cases") == [("open",)]
    assert audit(db)[-1] == ("safety", "joined")


@pytest.mark.parametrize("target", ["case", "new"])
@pytest.mark.parametrize("llm", [IN_ACTION_LLM], ids=["in-action"])
def test_d8_safety_under_prompt(
    triage_client: TestClient, db: Engine, llm: FakeLlm, target: str
) -> None:
    triage_client.get(f"/q/{C12}")
    token = send(triage_client, "no hot water").cookies["case_token"]
    calls = len(llm.calls)

    reply = post(triage_client, "smoke from the heater", target=target, offered=token)

    expected = [("open", False), ("held", True)] if target == "new" else [("held", True)]
    assert rows(db, "SELECT state, safety FROM cases ORDER BY id") == expected
    assert len(llm.calls) == calls
    assert demo_section("emergency").body in triage_client.get("/").text
    assert reply.status_code == 200

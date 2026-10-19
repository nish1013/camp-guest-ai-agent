import logging
from datetime import date, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from camp_agent.qr.qr_token import QrTokens
from tests.fakes import FakeClock
from tests.integration.intake_support import SECRET, RecordingGraph, count, send

QR = QrTokens(SECRET)
C12 = QR.issue("C12", date(2026, 10, 18), date(2026, 10, 25))


def case_scope(db: Engine) -> tuple[str | None, str | None]:
    with db.connect() as conn:
        row = conn.execute(text("SELECT scope_cabin, scope_source FROM cases")).one()
    return row.scope_cabin, row.scope_source


def test_us1_qr_sets_scope(client: TestClient, db: Engine) -> None:
    page = client.get(f"/q/{C12}")
    send(client, "no hot water")

    assert page.status_code == 200
    assert "Cabin C12, stay 18 Oct to 25 Oct" in page.text
    assert "surname" not in page.text.lower()
    assert case_scope(db) == ("C12", "qr")


def test_us1_ended_stay_no_scope(client: TestClient, db: Engine) -> None:
    ended = QR.issue("C12", date(2026, 10, 10), date(2026, 10, 17))

    page = client.get(f"/q/{ended}")
    send(client, "where is the pool")

    assert "Cabin C12" not in page.text
    assert case_scope(db) == (None, None)


def test_us1_scope_ends_with_stay(client: TestClient, db: Engine, clock: FakeClock) -> None:
    client.get(f"/q/{C12}")
    clock.advance(timedelta(days=7))

    send(client, "where is the pool")

    assert case_scope(db) == (None, None)


def test_us1_bad_signature_no_scope(
    client: TestClient, db: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    forged = QrTokens("other-secret").issue("C12", date(2026, 10, 18), date(2026, 10, 25))
    client.get(f"/q/{C12}")

    with caplog.at_level(logging.WARNING, logger="camp_agent.http.guest"):
        page = client.get(f"/q/{forged}")
    send(client, "where is the pool")

    assert "Cabin C12" not in page.text
    assert case_scope(db) == (None, None)
    assert "invalid QR token" in caplog.text


def test_us1_rescan_shows_open_case(client: TestClient) -> None:
    first = send(client, "where is the pool")

    page = client.get(f"/q/{C12}")

    assert f"/c/{first.cookies['case_token']}" in page.text
    assert "Received" in page.text


def test_us2_new_case(client: TestClient, db: Engine, graph: RecordingGraph) -> None:
    response = send(client, "Where is the pool?")

    token = response.cookies["case_token"]
    assert response.status_code == 200
    assert f"/c/{token}" in response.text
    assert "Received" in response.text
    assert (count(db, "cases"), count(db, "messages")) == (1, 1)
    assert graph.batches == [["Where is the pool?"]]


def test_us2_message_joins_case(client: TestClient, db: Engine) -> None:
    first = send(client, "Where is the pool?")
    second = send(client, "also the heater is off")

    assert second.cookies["case_token"] == first.cookies["case_token"]
    assert (count(db, "cases"), count(db, "messages")) == (1, 2)


def test_us2_unknown_cookie_new_case(client: TestClient, db: Engine) -> None:
    client.cookies.set("case_token", "forged")

    response = send(client, "Where is the pool?")

    assert response.cookies["case_token"] != "forged"
    assert count(db, "cases") == 1


def test_us2_retry_one_message_one_run(
    client: TestClient, db: Engine, graph: RecordingGraph
) -> None:
    key = str(uuid4())

    first = send(client, "no hot water", key)
    retry = send(client, "no hot water", key)

    assert retry.status_code == 200
    assert retry.cookies["case_token"] == first.cookies["case_token"]
    assert (count(db, "cases"), count(db, "messages")) == (1, 1)
    assert graph.batches == [["no hot water"]]


def test_us2_21st_message_is_429(client: TestClient, db: Engine, graph: RecordingGraph) -> None:
    for i in range(20):
        assert send(client, f"message {i}").status_code == 200

    refused = send(client, "message 21")

    assert refused.status_code == 429
    assert "Please try again in a few minutes" in refused.text
    assert count(db, "messages") == 20
    assert len(graph.batches) == 20


def test_us2_retry_after_limit_is_200(client: TestClient) -> None:
    key = str(uuid4())
    send(client, "message 0", key)
    for i in range(1, 20):
        send(client, f"message {i}")

    assert send(client, "message 0", key).status_code == 200


@pytest.mark.parametrize(
    "form",
    [
        {"text": "", "idempotency_key": str(uuid4())},
        {"text": "   ", "idempotency_key": str(uuid4())},
        {"text": "x" * 2001, "idempotency_key": str(uuid4())},
        {"text": "hello", "idempotency_key": "not-a-uuid"},
        {"text": "hello"},
    ],
    ids=["empty", "blank", "2001-chars", "bad-key", "no-key"],
)
def test_us2_malformed_is_422(client: TestClient, db: Engine, form: dict[str, str]) -> None:
    assert client.post("/messages", data=form).status_code == 422
    assert count(db, "messages") == 0


def test_us2_2000_chars_accepted(client: TestClient) -> None:
    assert send(client, "x" * 2000).status_code == 200

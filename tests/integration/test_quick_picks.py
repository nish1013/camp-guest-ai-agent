from datetime import date
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import Engine

from camp_agent.domain.route_guard import Category, Route
from camp_agent.domain.urgency import Urgency
from camp_agent.llm.llm_types import Classification
from camp_agent.qr.qr_token import QrTokens
from tests.fakes import FakeLlm
from tests.integration.intake_support import SECRET, count, rows

C12 = QrTokens(SECRET).issue("C12", date(2026, 10, 18), date(2026, 10, 25))
REFUND = "I want a refund for last night"
AS_QUESTION = Classification(category=Category.REFUND, route=Route.QUESTION, urgency=Urgency.NORMAL)


def send_pick(client: TestClient, text: str, pick: str) -> Response:
    return client.post(
        "/messages", data={"text": text, "idempotency_key": str(uuid4()), "pick": pick}
    )


def test_d51_pick_stored_on_new_request(client: TestClient, db: Engine) -> None:
    send_pick(client, "the shower is cold", "maintenance")
    send_pick(client, "and the sink", "cleaning")

    assert rows(db, "SELECT text, pick FROM messages ORDER BY id") == [
        ("the shower is cold", "maintenance"),
        ("and the sink", None),
    ]


def test_d51_unknown_pick_is_422(client: TestClient, db: Engine) -> None:
    assert send_pick(client, "hello", "refund").status_code == 422
    assert count(db, "messages") == 0


@pytest.mark.parametrize("llm", [FakeLlm(classes={REFUND: AS_QUESTION})], ids=["refund"])
def test_d36_refund_under_question_held(
    triage_client: TestClient, db: Engine, llm: FakeLlm
) -> None:
    triage_client.get(f"/q/{C12}")

    send_pick(triage_client, REFUND, "question")

    assert rows(db, "SELECT state, state_reason FROM cases") == [("held", "money")]
    assert rows(db, "SELECT kind, state FROM tasks") == [("money", "held")]
    assert rows(
        db,
        "SELECT detail->>'pick', detail->>'category' FROM audit_entries WHERE step = 'classify'",
    ) == [("question", "refund")]
    assert "Waiting on reception" in triage_client.get("/").text

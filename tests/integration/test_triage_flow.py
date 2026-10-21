from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from camp_agent.config import Settings
from camp_agent.domain.routing import Category, Route, Urgency
from camp_agent.llm.port import Classification, Verdict
from camp_agent.qr.qr_token import QrTokens
from tests.fakes import FakeLlm, SwitchableGuide, demo_section
from tests.integration.intake_support import SECRET, audit, count, rows, send

GUIDANCE = demo_section("emergency").body
C12 = QrTokens(SECRET).issue("C12", date(2026, 10, 18), date(2026, 10, 25))
REFUND = Classification(category=Category.REFUND, route=Route.FAULT, urgency=Urgency.NORMAL)


def case_row(db: Engine) -> tuple[object, ...]:
    return rows(db, "SELECT state, state_reason, safety, urgency FROM cases")[0]


def page_status(client: TestClient) -> str:
    return client.get("/").text


def test_us6_emergency_shown_and_held(triage_client: TestClient, db: Engine) -> None:
    send(triage_client, "smoke coming from the heater")

    assert case_row(db) == ("held", "emergency", True, "urgent")
    assert GUIDANCE in page_status(triage_client)


def test_us6_guidance_with_guide_down(
    triage_client: TestClient, db: Engine, guide: SwitchableGuide
) -> None:
    guide.down = True

    send(triage_client, "flood in the bathroom")

    assert case_row(db) == ("held", "emergency", True, "urgent")
    assert GUIDANCE in page_status(triage_client)


@pytest.mark.parametrize(
    "llm", [FakeLlm(verdicts={"gas smell lol": Verdict.SPAM})], ids=["spam-verdict"]
)
def test_i9_safety_wins_over_spam(triage_client: TestClient, db: Engine, llm: FakeLlm) -> None:
    send(triage_client, "gas smell lol")

    assert case_row(db) == ("held", "emergency", True, "urgent")
    assert llm.calls == []


@pytest.mark.parametrize(
    "llm", [FakeLlm(classes={"I want a refund for last night": REFUND})], ids=["refund"]
)
def test_us8_refund_held(triage_client: TestClient, db: Engine) -> None:
    triage_client.get(f"/q/{C12}")

    send(triage_client, "I want a refund for last night")

    assert case_row(db)[:2] == ("held", "money")
    assert rows(db, "SELECT kind, state FROM tasks") == [("money", "held")]
    assert "Waiting on reception" in page_status(triage_client)


@pytest.mark.parametrize(
    "llm",
    [FakeLlm(verdicts={"cheap watches www.example.biz": Verdict.SPAM})],
    ids=["spam"],
)
def test_us10_spam_parked_and_audited(triage_client: TestClient, db: Engine) -> None:
    send(triage_client, "cheap watches www.example.biz")

    assert case_row(db)[:2] == ("parked", "spam")
    assert count(db, "tasks") == 0
    assert audit(db) == [("safety", "clear"), ("verify", "spam"), ("park", "parked")]


@pytest.mark.parametrize("llm", [FakeLlm(down=True)], ids=["down"])
def test_us2_llm_down_with_reception(triage_client: TestClient, db: Engine, llm: FakeLlm) -> None:
    send(triage_client, "where is the pool")

    assert case_row(db)[:2] == ("held", "llm_failed")
    assert llm.calls == ["verify"] * Settings().llm_attempts
    assert "With reception" in page_status(triage_client)


def test_i13_every_routing_step_audited(triage_client: TestClient, db: Engine) -> None:
    send(triage_client, "where is the pool")

    assert audit(db) == [
        ("safety", "clear"),
        ("verify", "genuine"),
        ("split", "1"),
        ("classify", "question"),
        ("route_guard", "question"),
        ("answer", "no_section"),
        ("case", "closed"),
    ]

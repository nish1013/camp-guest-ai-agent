from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from camp_agent.domain.faults import FaultType
from camp_agent.domain.routing import Category, Route, Urgency
from camp_agent.llm.port import Classification
from camp_agent.qr.qr_token import QrTokens
from tests.fakes import FakeLlm
from tests.integration.intake_support import SECRET, rows, send
from tests.integration.staff_support import login

C12 = QrTokens(SECRET).issue("C12", date(2026, 10, 18), date(2026, 10, 25))
HOT_WATER = Classification(
    category=Category.MAINTENANCE,
    route=Route.FAULT,
    urgency=Urgency.URGENT,
    fault_type=FaultType.HOT_WATER,
)
FOLLOW_UP = "also the heater is off, call [phone]"


@pytest.fixture
def llm() -> FakeLlm:
    return FakeLlm(classes={"no hot water": HOT_WATER})


def test_us11_case_view_needs_login(triage_client: TestClient) -> None:
    reply = triage_client.get("/staff/cases/1", follow_redirects=False)

    assert reply.status_code == 303


def test_us11_unknown_case_404(triage_client: TestClient) -> None:
    login(triage_client)

    assert triage_client.get("/staff/cases/999").status_code == 404


def test_d14_joined_follow_up_shown_to_staff(triage_client: TestClient, db: Engine) -> None:
    triage_client.get(f"/q/{C12}")
    send(triage_client, "no hot water")
    send(triage_client, "also the heater is off, call 07700 900123")
    login(triage_client)
    case_id = rows(db, "SELECT id FROM cases")[0][0]

    page = triage_client.get(f"/staff/cases/{case_id}").text

    assert page.count("data-message") == 2
    assert FOLLOW_UP in page
    assert "07700" not in page
    assert "<td>joined</td>" in page
    assert "T1: open" in page

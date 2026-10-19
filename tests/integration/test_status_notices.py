import logging
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.ext.asyncio import AsyncEngine

from camp_agent.domain.route_guard import Category, Route
from camp_agent.domain.urgency import Urgency
from camp_agent.intake.apply_ticket_status import ApplyTicketStatus
from camp_agent.llm.llm_types import Classification
from camp_agent.qr.qr_token import QrTokens
from tests.fakes import FakeClock, FakeLlm, RecordingNotifications
from tests.integration.intake_support import SECRET, rows, send
from tests.integration.staff_support import login
from tests.integration.test_staff_resolve import resolve, version_of
from tests.integration.test_staff_tickets import demo_ticket, set_status, ticketed_case

C12 = QrTokens(SECRET).issue("C12", date(2026, 10, 18), date(2026, 10, 25))
REFUND = "I want a refund for last night"
MONEY = Classification(category=Category.REFUND, route=Route.MONEY, urgency=Urgency.NORMAL)
REFUND_LLM = FakeLlm(classes={REFUND: MONEY})
RECEIVED = "Status: Received"
WAITING = "Status: Waiting on reception"


class SpyWatch:
    def __init__(self) -> None:
        self.cases: list[int] = []

    async def changed(self, case_id: int) -> None:
        self.cases.append(case_id)


def held_refund(client: TestClient, db: Engine) -> tuple[int, str]:
    client.get(f"/q/{C12}")
    send(client, REFUND)
    login(client)
    case_id, step_id = rows(db, "SELECT case_id, step_id FROM tasks")[0]
    assert isinstance(case_id, int) and isinstance(step_id, str)
    return case_id, step_id


@pytest.mark.parametrize("llm", [REFUND_LLM], ids=["refund"])
def test_d22_graph_step_notifies_on_change(
    triage_client: TestClient, db: Engine, notices: RecordingNotifications
) -> None:
    held_refund(triage_client, db)

    assert notices.statuses() == [RECEIVED, WAITING]
    assert {notice.case_id for notice in notices.notices} == {1}


@pytest.mark.parametrize("llm", [REFUND_LLM], ids=["refund"])
def test_d22_staff_resolve_notifies(
    triage_client: TestClient, db: Engine, notices: RecordingNotifications
) -> None:
    case_id, step_id = held_refund(triage_client, db)
    stale = version_of(db) - 1

    assert resolve(triage_client, case_id, stale, "approve", step_id=step_id).status_code == 409
    assert notices.statuses() == [RECEIVED, WAITING]

    resolve(triage_client, case_id, version_of(db), "approve", step_id=step_id)
    assert notices.statuses() == [RECEIVED, WAITING, "Status: Closed"]


def test_d22_ticket_status_notifies_once(
    client: TestClient, db: Engine, notices: RecordingNotifications
) -> None:
    ticketed_case(db)
    demo_ticket(db)
    login(client)

    set_status(client, "in_progress")
    set_status(client, "in_progress")

    assert rows(db, "SELECT ticket_version FROM tasks") == [(3,)]
    assert len(notices.notices) == 1
    assert "heater broken: Maintenance is working on it" in notices.statuses()[0]


@pytest.mark.anyio
async def test_d22_repeat_event_no_call(
    db: Engine, async_db: AsyncEngine, clock: FakeClock
) -> None:
    case_id, _ = ticketed_case(db)
    with db.begin() as conn:
        for status, version in (("in_progress", 2), ("in_progress", 2), ("open", 1)):
            conn.execute(
                text(
                    "INSERT INTO ticket_events (ticket_ref, status, version) VALUES ('T1', :s, :v)"
                ),
                {"s": status, "v": version},
            )
    watch = SpyWatch()

    await ApplyTicketStatus(async_db, clock, watch).handle_pending()

    assert watch.cases == [case_id]


@pytest.mark.parametrize("llm", [REFUND_LLM], ids=["refund"])
def test_d22_port_down_case_unchanged(
    triage_client: TestClient,
    db: Engine,
    notices: RecordingNotifications,
    caplog: pytest.LogCaptureFixture,
) -> None:
    notices.down = True

    with caplog.at_level(logging.ERROR, logger="camp_agent.http.status_notifier"):
        case_id, step_id = held_refund(triage_client, db)
        assert rows(db, "SELECT state, state_reason FROM cases") == [("held", "money")]
        reply = resolve(triage_client, case_id, version_of(db), "approve", step_id=step_id)

    assert reply.status_code == 303
    assert rows(db, "SELECT state FROM cases") == [("closed",)]
    assert notices.notices == []
    assert "status notice failed" in caplog.text

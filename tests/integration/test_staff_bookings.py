from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import Engine, text

from camp_agent.domain.routing import Category, Route, Urgency
from camp_agent.llm.port import Classification
from camp_agent.qr.qr_token import QrTokens
from tests.fakes import FakeClock, FakeLlm
from tests.integration.intake_support import SECRET, audit, rows, send
from tests.integration.staff_support import login

C12 = QrTokens(SECRET).issue("C12", date(2026, 10, 18), date(2026, 10, 25))
TABLE = "table for 4 at 19:30 tonight"
DINNER = Classification(category=Category.RESTAURANT, route=Route.TABLE, urgency=Urgency.NORMAL)
BOOKED = "Booked: table for 4 at 19:30."
DECLINED = "The restaurant could not take this booking."
CHANGED = "This case changed since you opened it."


@pytest.fixture
def llm() -> FakeLlm:
    return FakeLlm(classes={TABLE: DINNER})


def requested(client: TestClient, db: Engine) -> tuple[int, int, int]:
    client.get(f"/q/{C12}")
    send(client, TABLE)
    login(client)
    task_id, case_id, version = rows(
        db, "SELECT t.id, c.id, c.version FROM tasks t JOIN cases c ON c.id = t.case_id"
    )[0]
    assert isinstance(task_id, int) and isinstance(case_id, int) and isinstance(version, int)
    return task_id, case_id, version


def decide(client: TestClient, task_id: int, decision: str, version: int) -> Response:
    return client.post(
        f"/staff/bookings/{task_id}/status",
        data={"decision": decision, "version": str(version)},
        follow_redirects=False,
    )


def case_row(db: Engine) -> tuple[object, ...]:
    return rows(db, "SELECT state, closed_at IS NOT NULL FROM cases")[0]


def test_us13_confirm_reads_booked(triage_client: TestClient, db: Engine) -> None:
    task_id, case_id, version = requested(triage_client, db)

    reply = decide(triage_client, task_id, "confirm", version)

    assert reply.status_code == 303
    assert reply.headers["location"] == f"/staff/cases/{case_id}"
    assert BOOKED in triage_client.get("/").text
    assert case_row(db) == ("closed", True)
    assert audit(db)[-1] == ("booking_status", "booking_confirmed")


def test_us13_decline_reads_declined(triage_client: TestClient, db: Engine) -> None:
    task_id, _, version = requested(triage_client, db)

    decide(triage_client, task_id, "decline", version)

    page = triage_client.get("/").text
    assert DECLINED in page
    assert "Booked" not in page


@pytest.mark.parametrize("second", ["confirm", "decline"])
def test_us13_answered_request_conflicts(
    triage_client: TestClient, db: Engine, second: str
) -> None:
    task_id, _, version = requested(triage_client, db)
    decide(triage_client, task_id, "confirm", version)

    reply = decide(triage_client, task_id, second, version + 1)

    assert reply.status_code == 409
    assert CHANGED in reply.text
    assert rows(db, "SELECT state FROM tasks") == [("booking_confirmed",)]


def test_i11_stale_form_conflicts(triage_client: TestClient, db: Engine) -> None:
    task_id, _, version = requested(triage_client, db)

    reply = decide(triage_client, task_id, "confirm", version - 1)

    assert reply.status_code == 409
    assert rows(db, "SELECT state FROM tasks") == [("booking_requested",)]


def test_i11_run_holds_lease_conflicts(
    triage_client: TestClient, db: Engine, clock: FakeClock
) -> None:
    task_id, _, version = requested(triage_client, db)
    with db.begin() as conn:
        conn.execute(
            text("UPDATE cases SET run_lease_owner = gen_random_uuid(), run_lease_until = :until"),
            {"until": clock.now() + timedelta(seconds=60)},
        )

    reply = decide(triage_client, task_id, "confirm", version)

    assert reply.status_code == 409
    assert rows(db, "SELECT state FROM tasks") == [("booking_requested",)]


def test_i11_open_task_keeps_case_open(triage_client: TestClient, db: Engine) -> None:
    task_id, case_id, version = requested(triage_client, db)
    with db.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO tasks (case_id, step_id, kind, urgency, state, summary)"
                " VALUES (:case_id, 'm9/t0', 'money', 'normal', 'held', 'refund')"
            ),
            {"case_id": case_id},
        )

    decide(triage_client, task_id, "confirm", version)

    assert case_row(db) == ("open", False)


def test_us13_unknown_booking_404(triage_client: TestClient) -> None:
    login(triage_client)

    assert decide(triage_client, 999, "confirm", 0).status_code == 404


def test_us13_needs_login(triage_client: TestClient) -> None:
    assert decide(triage_client, 1, "confirm", 0).status_code == 303


def closed_case(db: Engine, closed_at: datetime) -> str:
    with db.begin() as conn:
        token: str = conn.execute(
            text(
                "INSERT INTO cases (case_token, state, closed_at) VALUES ('K1', 'closed', :at)"
                " RETURNING case_token"
            ),
            {"at": closed_at},
        ).scalar_one()
    return token


@pytest.mark.parametrize(("hours", "cases"), [(3, 1), (25, 2)], ids=["3h-reopens", "25h-new"])
def test_d20_reply_reopens_within_day(
    triage_client: TestClient, db: Engine, clock: FakeClock, hours: int, cases: int
) -> None:
    token = closed_case(db, clock.now() - timedelta(hours=hours))
    triage_client.cookies.set("case_token", token)

    reply = send(triage_client, "When does the pool open?")

    assert len(rows(db, "SELECT id FROM cases")) == cases
    assert (reply.cookies["case_token"] == token) is (cases == 1)
    assert (("case", "reopened") in audit(db)) is (cases == 1)


def test_d20_reopen_is_audited(triage_client: TestClient, db: Engine, clock: FakeClock) -> None:
    closed_case(db, clock.now() - timedelta(hours=3))
    triage_client.cookies.set("case_token", "K1")

    send(triage_client, "When does the pool open?")

    assert audit(db)[0] == ("case", "reopened")

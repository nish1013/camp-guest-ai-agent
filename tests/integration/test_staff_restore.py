from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import Engine, text

from camp_agent.domain.faults import FaultType
from camp_agent.domain.routing import Category, Route, Urgency
from camp_agent.llm.port import Classification, GuideAnswer, Verdict
from tests.fakes import FakeClock, FakeLlm, SwitchableStays
from tests.integration.intake_support import audit, rows, send
from tests.integration.staff_support import login

SPAM = "cheap watches www.example.biz"
SPAM_AGAIN = "cheap pills www.example.biz"
FAULT = "no hot water"
TABLE = "table for 4 at 19:30 tonight"
POOL = "When does the pool open?"
PHONE = "Call 01632 960124 to ask about a table."
HOT_WATER = Classification(
    category=Category.MAINTENANCE,
    route=Route.FAULT,
    urgency=Urgency.URGENT,
    fault_type=FaultType.HOT_WATER,
)
DINNER = Classification(category=Category.RESTAURANT, route=Route.TABLE, urgency=Urgency.NORMAL)


@pytest.fixture
def llm() -> FakeLlm:
    return FakeLlm(
        verdicts={SPAM: Verdict.SPAM, SPAM_AGAIN: Verdict.SPAM},
        classes={FAULT: HOT_WATER, TABLE: DINNER},
        answers={TABLE: GuideAnswer(text=PHONE, section_id="restaurant")},
    )


def case_id_and_version(db: Engine) -> tuple[int, int]:
    case_id, version = rows(db, "SELECT id, version FROM cases")[0]
    assert isinstance(case_id, int) and isinstance(version, int)
    return case_id, version


def restore(client: TestClient, db: Engine, booking_ref: str = "") -> Response:
    case_id, version = case_id_and_version(db)
    return client.post(
        f"/staff/cases/{case_id}/restore",
        data={"version": str(version), "booking_ref": booking_ref},
        follow_redirects=False,
    )


def park_unverified(client: TestClient, text_: str) -> None:
    token: str = send(client, text_).cookies["case_token"]
    for _ in range(3):
        client.post(f"/c/{token}/step-up", data={"surname": "Müller", "booking_ref": "BK-1"})


def case_row(db: Engine) -> tuple[object, ...]:
    return rows(db, "SELECT state, state_reason, scope_cabin, scope_source FROM cases")[0]


def test_us14_spam_restore_triages_again(
    triage_client: TestClient, db: Engine, llm: FakeLlm
) -> None:
    send(triage_client, SPAM)
    assert case_row(db)[:2] == ("parked", "spam")
    login(triage_client)

    reply = restore(triage_client, db)

    assert reply.status_code == 303
    assert case_row(db)[:2] == ("closed", None)
    assert llm.calls.count("verify") == 1
    assert ("verify", "restored") in audit(db)
    assert rows(db, "SELECT kind, state FROM tasks") == [("question", "done")]


def test_us14_unverified_restore_sets_staff_scope(triage_client: TestClient, db: Engine) -> None:
    park_unverified(triage_client, FAULT)
    assert case_row(db) == ("parked", "verification", None, None)
    login(triage_client)

    reply = restore(triage_client, db, "BK 48213")

    assert reply.status_code == 303
    assert case_row(db) == ("open", None, "C12", "staff")
    assert rows(db, "SELECT kind, state, ticket_ref FROM tasks") == [("fault", "ticketed", "T1")]
    assert all("48213" not in str(row) for row in rows(db, "SELECT detail FROM audit_entries"))


def test_i10_restored_case_not_parked_again(triage_client: TestClient, db: Engine) -> None:
    park_unverified(triage_client, FAULT)
    login(triage_client)
    restore(triage_client, db, "BK-48213")
    token = rows(db, "SELECT case_token FROM cases")[0][0]

    triage_client.post(f"/c/{token}/step-up", data={"surname": "x", "booking_ref": "BK-1"})

    assert case_row(db)[:2] == ("open", None)


@pytest.mark.parametrize(
    ("booking_ref", "notice"),
    [("", "needs the booking reference"), ("BK-1", "No booking with that reference.")],
    ids=["missing", "unknown"],
)
def test_us14_unverified_needs_known_booking(
    triage_client: TestClient, db: Engine, booking_ref: str, notice: str
) -> None:
    park_unverified(triage_client, FAULT)
    login(triage_client)

    reply = restore(triage_client, db, booking_ref)

    assert reply.status_code == 422
    assert notice in reply.text
    assert case_row(db)[:2] == ("parked", "verification")


def test_d41_stays_down_restore_refused(
    triage_client: TestClient, db: Engine, stays: SwitchableStays
) -> None:
    park_unverified(triage_client, FAULT)
    login(triage_client)
    stays.down = True

    reply = restore(triage_client, db, "BK-48213")

    assert reply.status_code == 503
    assert case_row(db)[:2] == ("parked", "verification")


def test_d33_restore_open_case_conflicts(triage_client: TestClient, db: Engine) -> None:
    send(triage_client, POOL)
    login(triage_client)

    assert restore(triage_client, db).status_code == 409


def test_d33_double_restore_conflicts(triage_client: TestClient, db: Engine) -> None:
    send(triage_client, SPAM)
    login(triage_client)
    case_id, version = case_id_and_version(db)
    data = {"version": str(version)}

    first = triage_client.post(f"/staff/cases/{case_id}/restore", data=data)
    second = triage_client.post(f"/staff/cases/{case_id}/restore", data=data)

    assert (first.status_code, second.status_code) == (200, 409)
    assert audit(db).count(("restore", "spam")) == 1


def test_i8_restore_during_run_409(triage_client: TestClient, db: Engine, clock: FakeClock) -> None:
    send(triage_client, SPAM)
    login(triage_client)
    with db.begin() as conn:
        conn.execute(
            text("UPDATE cases SET run_lease_owner = gen_random_uuid(), run_lease_until = :until"),
            {"until": clock.now() + timedelta(seconds=60)},
        )

    assert restore(triage_client, db).status_code == 409
    assert case_row(db)[:2] == ("parked", "spam")


def test_d33_parked_twice_requeues_latest(
    triage_client: TestClient, db: Engine, llm: FakeLlm
) -> None:
    send(triage_client, SPAM)
    login(triage_client)
    restore(triage_client, db)
    send(triage_client, SPAM_AGAIN)
    assert case_row(db)[:2] == ("parked", "spam")

    restore(triage_client, db)

    assert case_row(db)[:2] == ("closed", None)
    assert (llm.calls.count("verify"), llm.calls.count("classify")) == (2, 2)
    assert audit(db).count(("verify", "restored")) == 2
    assert rows(db, "SELECT summary FROM tasks ORDER BY id") == [(SPAM,), (SPAM_AGAIN,)]


def test_d33_messages_while_parked_requeued(
    triage_client: TestClient, db: Engine, llm: FakeLlm
) -> None:
    send(triage_client, SPAM)
    send(triage_client, POOL)
    assert ("safety", "stop_parked") in audit(db)
    login(triage_client)

    restore(triage_client, db)

    assert llm.calls.count("verify") == 1
    assert rows(db, "SELECT summary, state FROM tasks") == [(f"{SPAM}\n{POOL}", "done")]
    assert rows(db, "SELECT count(*) FROM messages WHERE handled_at IS NULL OR parked") == [(0,)]


def test_d19_restore_ended_stay_answers_table(
    triage_client: TestClient, db: Engine, llm: FakeLlm
) -> None:
    park_unverified(triage_client, TABLE)
    login(triage_client)

    restore(triage_client, db, "BK-39950")

    assert case_row(db) == ("closed", None, "C12", "staff")
    assert rows(db, "SELECT kind, state, answer FROM tasks") == [("question", "done", PHONE)]
    assert "draft_table" not in llm.calls
    assert PHONE in triage_client.get("/").text

import threading
from datetime import date

import anyio
import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import Engine

from camp_agent.domain.fault_type import FaultType
from camp_agent.domain.route_guard import Category, Route
from camp_agent.domain.urgency import Urgency
from camp_agent.llm.llm_types import Classification, TicketArgs, Verdict
from camp_agent.qr.qr_token import QrTokens
from tests.fakes import FakeLlm
from tests.integration.intake_support import SECRET, audit, rows, send
from tests.integration.staff_support import login

C12 = QrTokens(SECRET).issue("C12", date(2026, 10, 18), date(2026, 10, 25))
REFUND = "I want a refund for last night"
HEATER = "the heater is broken"
FOLLOW_UP = "any news?"
MONEY = Classification(category=Category.REFUND, route=Route.MONEY, urgency=Urgency.NORMAL)
HEATING = Classification(
    category=Category.MAINTENANCE,
    route=Route.FAULT,
    urgency=Urgency.NORMAL,
    fault_type=FaultType.HEATING,
)
BAD = TicketArgs(tool="create_ticket", cabin="C14", summary=HEATER)
DECLINED = "Reception has declined this request"
CHANGED = "This case changed since you opened it."


class GatedLlm(FakeLlm):
    def __init__(self) -> None:
        super().__init__(classes={REFUND: MONEY, HEATER: HEATING}, drafts={HEATER: [BAD, BAD]})
        self.gated: set[str] = set()
        self.entered = threading.Event()
        self.gate = threading.Event()

    async def verify(self, text: str) -> Verdict:
        if text in self.gated:
            self.entered.set()
            await anyio.to_thread.run_sync(self.gate.wait)
        return await super().verify(text)


@pytest.fixture
def llm() -> GatedLlm:
    return GatedLlm()


def held_case(client: TestClient, db: Engine, text: str) -> tuple[int, int, str]:
    client.get(f"/q/{C12}")
    send(client, text)
    login(client)
    case_id, version, step_id = rows(
        db, "SELECT c.id, c.version, t.step_id FROM cases c JOIN tasks t ON t.case_id = c.id"
    )[0]
    assert isinstance(case_id, int) and isinstance(version, int) and isinstance(step_id, str)
    return case_id, version, step_id


def resolve(client: TestClient, case_id: int, version: int, action: str, **fields: str) -> Response:
    data = {"action": action, "version": str(version), **fields}
    return client.post(f"/staff/cases/{case_id}/resolve", data=data, follow_redirects=False)


def version_of(db: Engine) -> int:
    version = rows(db, "SELECT version FROM cases")[0][0]
    assert isinstance(version, int)
    return version


def test_us12_approve_refund_continues(triage_client: TestClient, db: Engine) -> None:
    case_id, version, step_id = held_case(triage_client, db, REFUND)
    assert rows(db, "SELECT state, state_reason FROM cases") == [("held", "money")]

    reply = resolve(triage_client, case_id, version, "approve", step_id=step_id)

    assert reply.status_code == 303
    assert rows(db, "SELECT kind, state FROM tasks") == [("money", "done")]
    assert rows(db, "SELECT state, held_at FROM cases")[0][0] == "closed"
    assert audit(db)[-1] == ("resolve", "approved")


def test_us12_edit_urgency_then_approve(triage_client: TestClient, db: Engine) -> None:
    case_id, version, step_id = held_case(triage_client, db, HEATER)
    assert rows(db, "SELECT state, state_reason FROM cases") == [("held", "fault_review")]

    resolve(
        triage_client,
        case_id,
        version,
        "approve",
        step_id=step_id,
        category="maintenance",
        urgency="urgent",
    )

    assert rows(db, "SELECT urgency, cabin FROM demo_tickets") == [("urgent", "C12")]
    assert rows(db, "SELECT state, urgency FROM tasks") == [("ticketed", "urgent")]
    assert rows(db, "SELECT state, urgency FROM cases") == [("open", "urgent")]


def test_us12_reject_declines_task(triage_client: TestClient, db: Engine) -> None:
    case_id, version, step_id = held_case(triage_client, db, HEATER)

    resolve(triage_client, case_id, version, "reject", step_id=step_id)

    assert rows(db, "SELECT state FROM tasks") == [("rejected",)]
    assert rows(db, "SELECT count(*) FROM demo_tickets") == [(0,)]
    assert DECLINED in triage_client.get("/").text


def test_us12_no_free_text_to_guest(triage_client: TestClient, db: Engine) -> None:
    case_id, version, step_id = held_case(triage_client, db, REFUND)
    page = triage_client.get(f"/staff/cases/{case_id}").text

    resolve(triage_client, case_id, version, "approve", step_id=step_id, reply="Refund sent!")

    assert "<textarea" not in page
    assert "Refund sent!" not in triage_client.get("/").text


def test_us12_edit_on_money_refused(triage_client: TestClient, db: Engine) -> None:
    case_id, version, step_id = held_case(triage_client, db, REFUND)

    reply = resolve(triage_client, case_id, version, "approve", step_id=step_id, urgency="urgent")

    assert reply.status_code == 422
    assert rows(db, "SELECT state FROM tasks") == [("held",)]


def test_us12_needs_login(triage_client: TestClient) -> None:
    assert resolve(triage_client, 1, 0, "approve").status_code == 303


def test_us12_double_resolve_conflicts(triage_client: TestClient, db: Engine) -> None:
    case_id, version, step_id = held_case(triage_client, db, REFUND)
    resolve(triage_client, case_id, version, "approve", step_id=step_id)

    stale = resolve(triage_client, case_id, version, "reject", step_id=step_id)
    fresh = resolve(triage_client, case_id, version_of(db), "reject", step_id=step_id)

    assert (stale.status_code, fresh.status_code) == (409, 409)
    assert CHANGED in stale.text
    assert rows(db, "SELECT state FROM tasks") == [("done",)]


def test_d20_case_hold_without_task_closes(
    triage_client: TestClient, db: Engine, llm: GatedLlm
) -> None:
    llm.down_for.add("verify")
    triage_client.get(f"/q/{C12}")
    send(triage_client, REFUND)
    login(triage_client)
    assert rows(db, "SELECT state, state_reason FROM cases") == [("held", "llm_failed")]
    case_id = rows(db, "SELECT id FROM cases")[0][0]
    assert isinstance(case_id, int)

    with_step = resolve(triage_client, case_id, version_of(db), "approve", step_id="m1/t0")
    reply = resolve(triage_client, case_id, version_of(db), "approve")

    assert with_step.status_code == 409
    assert reply.status_code == 303
    assert rows(db, "SELECT state FROM cases") == [("closed",)]


def test_i11_one_of_two_held_stays_held(triage_client: TestClient, db: Engine) -> None:
    case_id, _, step_id = held_case(triage_client, db, REFUND)
    send(triage_client, HEATER)
    assert rows(db, "SELECT state FROM tasks ORDER BY id") == [("held",), ("held",)]

    resolve(triage_client, case_id, version_of(db), "approve", step_id=step_id)

    assert rows(db, "SELECT state, state_reason FROM cases") == [("held", "money")]


def test_i8_staff_resolve_during_run_409(
    triage_client: TestClient, db: Engine, llm: GatedLlm
) -> None:
    case_id, _, step_id = held_case(triage_client, db, REFUND)
    llm.gated.add(FOLLOW_UP)
    guest = threading.Thread(target=send, args=(triage_client, FOLLOW_UP))
    guest.start()
    assert llm.entered.wait(5)

    during = resolve(triage_client, case_id, version_of(db), "approve", step_id=step_id)
    llm.gate.set()
    guest.join(5)
    after = resolve(triage_client, case_id, version_of(db), "approve", step_id=step_id)

    assert during.status_code == 409
    assert after.status_code == 303
    assert rows(db, "SELECT state FROM tasks ORDER BY id")[0] == ("done",)

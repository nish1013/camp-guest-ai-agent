import threading
from datetime import date, timedelta

import anyio
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncEngine

from camp_agent.db.cases import CaseRepository
from camp_agent.domain.routing import Category, Route, Urgency
from camp_agent.llm.port import Classification, Verdict
from camp_agent.qr.qr_token import QrTokens
from tests.fakes import FakeClock, FakeLlm
from tests.integration.intake_support import SECRET, audit, rows, send

C12 = QrTokens(SECRET).issue("C12", date(2026, 10, 18), date(2026, 10, 25))
POOL = "When does the pool open?"
SAUNA = "Is there a sauna?"
BOTH = "When does the pool open, and I want a refund"
REFUND = "I want a refund"
MONEY = Classification(category=Category.REFUND, route=Route.MONEY, urgency=Urgency.NORMAL)


class GatedLlm(FakeLlm):
    def __init__(self) -> None:
        super().__init__(splits={BOTH: [POOL, REFUND]}, classes={REFUND: MONEY})
        self.entered = threading.Event()
        self.gate = threading.Event()

    async def verify(self, text: str) -> Verdict:
        if text == POOL and not self.gate.is_set():
            self.entered.set()
            await anyio.to_thread.run_sync(self.gate.wait)
        return await super().verify(text)


@pytest.fixture
def llm() -> GatedLlm:
    llm = GatedLlm()
    llm.gate.set()
    return llm


def case_states(db: Engine) -> list[tuple[object, ...]]:
    return rows(db, "SELECT state FROM cases ORDER BY id")


def test_d20_answered_question_closes_case(triage_client: TestClient, db: Engine) -> None:
    send(triage_client, POOL)

    assert case_states(db) == [("closed",)]
    assert rows(db, "SELECT kind, state FROM tasks") == [("question", "done")]
    assert audit(db)[-1] == ("case", "closed")


def test_d20_answer_with_held_task_stays_open(triage_client: TestClient, db: Engine) -> None:
    triage_client.get(f"/q/{C12}")
    send(triage_client, BOTH)

    assert rows(db, "SELECT kind, state FROM tasks ORDER BY id") == [
        ("question", "done"),
        ("money", "held"),
    ]
    assert rows(db, "SELECT state, state_reason FROM cases") == [("held", "money")]
    assert ("case", "closed") not in audit(db)


def test_d20_reply_reopens_then_closes_again(
    triage_client: TestClient, db: Engine, clock: FakeClock
) -> None:
    send(triage_client, POOL)
    clock.advance(timedelta(hours=3))

    send(triage_client, SAUNA)

    assert case_states(db) == [("closed",)]
    assert rows(db, "SELECT count(*) FROM tasks WHERE state = 'done'") == [(2,)]
    assert [e for e in audit(db) if e[0] == "case"] == [
        ("case", "closed"),
        ("case", "reopened"),
        ("case", "closed"),
    ]


def test_d6_message_queued_during_run_not_lost(
    triage_client: TestClient, db: Engine, llm: GatedLlm
) -> None:
    llm.gate.clear()
    first = threading.Thread(target=send, args=(triage_client, POOL))
    first.start()
    assert llm.entered.wait(5)

    send(triage_client, SAUNA)
    llm.gate.set()
    first.join(5)

    assert case_states(db) == [("closed",)]
    assert rows(db, "SELECT summary, state FROM tasks ORDER BY id") == [
        (POOL, "done"),
        (SAUNA, "done"),
    ]
    assert rows(db, "SELECT count(*) FROM messages WHERE handled_at IS NULL") == [(0,)]
    assert ("safety", "reopened") in audit(db)


@pytest.mark.anyio
async def test_d4_closed_case_not_offered(
    triage_client: TestClient, db: Engine, async_db: AsyncEngine
) -> None:
    token: str = send(triage_client, POOL).cookies["case_token"]

    async with async_db.connect() as conn:
        assert await CaseRepository(conn).find_open_by_token(token) is None

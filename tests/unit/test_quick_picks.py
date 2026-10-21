import pytest

from camp_agent.domain.cases import CaseState, StateReason
from camp_agent.domain.guest_status import QuickPick
from camp_agent.domain.routing import Category, Route, TaskKind, TaskState, Urgency
from camp_agent.graph.triage import PendingMessage
from camp_agent.llm.prompts import classify_input
from tests.fakes import FakeLlm
from tests.unit.triage_support import CASE, graph_for, new_store, proposal

pytestmark = pytest.mark.anyio

REFUND = "I want a refund for last night"


async def test_d36_refund_under_question_held() -> None:
    llm = FakeLlm(classes={REFUND: proposal(Category.REFUND, Route.QUESTION, Urgency.NORMAL)})
    store = new_store()

    await graph_for(llm, store).run(CASE, [PendingMessage(1, REFUND, pick=QuickPick.QUESTION)])

    status = store.status(CASE)
    assert (status.state, status.reason) == (CaseState.HELD, StateReason.MONEY)
    assert [(t.kind, t.state) for t in store.tasks] == [(TaskKind.MONEY, TaskState.HELD)]
    assert "answer" not in llm.calls


async def test_d51_pick_audited_beside_category() -> None:
    llm = FakeLlm()
    store = new_store()

    await graph_for(llm, store).run(
        CASE, [PendingMessage(1, "where is the pool", pick=QuickPick.RECEPTION)]
    )

    classified = next(entry for entry in store.audit if entry.step == "classify")
    assert llm.hints == [QuickPick.RECEPTION]
    assert (classified.decision, classified.detail["category"], classified.detail["pick"]) == (
        "question",
        "information",
        "reception",
    )


async def test_d51_no_pick_no_hint() -> None:
    llm = FakeLlm()
    store = new_store()

    await graph_for(llm, store).run(CASE, [PendingMessage(1, "where is the pool")])

    classified = next(entry for entry in store.audit if entry.step == "classify")
    assert llm.hints == [None]
    assert "pick" not in classified.detail


async def test_d51_batch_takes_first_pick() -> None:
    llm = FakeLlm()
    store = new_store()

    await graph_for(llm, store).run(
        CASE,
        [PendingMessage(1, "where is the pool", pick=QuickPick.QUESTION), PendingMessage(2, "ta")],
    )

    assert llm.hints == [QuickPick.QUESTION]


def test_d51_hint_framed_in_input() -> None:
    assert classify_input("no hot water", None) == "no hot water"
    assert classify_input("no hot water", QuickPick.CLEANING) == (
        "Topic picked: Cleaning\nGuest intent: no hot water"
    )

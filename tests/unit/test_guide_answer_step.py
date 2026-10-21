from collections.abc import Sequence

import pytest

from camp_agent.domain.cases import CaseState, StateReason
from camp_agent.domain.citation_check import GUIDE_DOWN, NO_INFORMATION
from camp_agent.domain.routing import Category, Route, TaskKind, Urgency
from camp_agent.graph.triage import TaskAnswer
from camp_agent.guide.port import GuideSection
from camp_agent.llm.port import GuideAnswer, LlmError
from tests.fakes import FakeLlm, demo_guide
from tests.unit.triage_support import CASE, RECEPTION, new_store, proposal, steps, triage

pytestmark = pytest.mark.anyio

POOL = "When does the pool open?"
SAUNA = "Is there a sauna?"
NO_INFO = f"{NO_INFORMATION} {RECEPTION}"


class AnswerDownLlm(FakeLlm):
    async def answer(self, question: str, sections: Sequence[GuideSection]) -> GuideAnswer:
        self.calls.append("answer")
        raise LlmError("down")


async def test_us3_answer_cites_section() -> None:
    llm = FakeLlm(answers={POOL: GuideAnswer(text="08:00-20:00", section_id="pool-hours")})

    store = await triage(llm, POOL)

    assert store.answers == [TaskAnswer("m1/t0", "08:00-20:00", "pool-hours")]
    assert [t.kind for t in store.tasks] == [TaskKind.QUESTION]
    assert "pool-hours" in llm.offered
    assert steps(store)[-3:] == ["route_guard:question", "answer:cited", "case:closed"]


async def test_us3_no_section_gives_reception() -> None:
    store = await triage(FakeLlm(), SAUNA)

    assert store.answers == [TaskAnswer("m1/t0", NO_INFO, None)]
    assert steps(store)[-2] == "answer:no_section"


async def test_us3_missing_section_withheld() -> None:
    llm = FakeLlm(answers={SAUNA: GuideAnswer(text="09:00-17:00", section_id="spa-hours")})

    store = await triage(llm, SAUNA)

    assert store.answers == [TaskAnswer("m1/t0", NO_INFO, None)]
    assert steps(store)[-2] == "answer:withheld"
    assert store.audit[-2].detail == {"step_id": "m1/t0", "proposed": "spa-hours"}


async def test_us3_no_scope_answered() -> None:
    llm = FakeLlm(answers={POOL: GuideAnswer(text="08:00-20:00", section_id="pool-hours")})

    store = await triage(llm, POOL, store=new_store(scope=None))

    assert store.answers == [TaskAnswer("m1/t0", "08:00-20:00", "pool-hours")]
    assert store.status(CASE).state is CaseState.CLOSED


async def test_d42_guide_down_gives_reception() -> None:
    guide = demo_guide()
    guide.down = True
    llm = FakeLlm()

    store = await triage(llm, POOL, guide=guide)

    assert store.answers == [TaskAnswer("m1/t0", f"{GUIDE_DOWN} {RECEPTION}", None)]
    assert "answer" not in llm.calls
    assert steps(store)[-2] == "answer:guide_down"


async def test_d16_answer_llm_down_held() -> None:
    store = await triage(AnswerDownLlm(), POOL)

    status = store.status(CASE)
    assert (status.state, status.reason) == (CaseState.HELD, StateReason.LLM_FAILED)
    assert store.answers == []
    assert store.audit[-1].detail == {"failed_step": "answer"}


async def test_us2_question_then_fault() -> None:
    text = "When does the pool open, and the tap leaks"
    leak = proposal(Category.MAINTENANCE, Route.FAULT, Urgency.URGENT)
    llm = FakeLlm(splits={text: [POOL, "the tap leaks"]}, classes={"the tap leaks": leak})

    store = await triage(llm, text)

    assert [a.step_id for a in store.answers] == ["m1/t0"]
    assert steps(store)[2:] == [
        "split:2",
        "classify:question",
        "route_guard:question",
        "answer:no_section",
        "classify:fault",
        "route_guard:fault",
        "same:none",
        "ticket:created",
    ]

import pytest

from camp_agent.domain.case_state import CaseState, StateReason
from camp_agent.domain.guest_status import (
    CLARIFY,
    RECEIVED,
    WAITING_ON_RECEPTION,
    WITH_RECEPTION,
    guest_status,
)
from camp_agent.domain.route_guard import Category, Route, TaskKind, TaskState
from camp_agent.domain.urgency import Urgency
from camp_agent.graph.triage_types import StepRecord
from camp_agent.llm.llm_types import Verdict
from tests.fakes import FakeLlm, InMemoryTriageStore
from tests.unit.triage_support import CASE, new_store, proposal, steps, triage

pytestmark = pytest.mark.anyio

GUIDANCE = "Call 999 now."
REFUND = proposal(Category.REFUND, Route.MONEY, Urgency.NORMAL)
HOT_WATER = proposal(Category.MAINTENANCE, Route.FAULT, Urgency.URGENT)
DINNER = proposal(Category.RESTAURANT, Route.TABLE, Urgency.NORMAL)


@pytest.mark.parametrize("text", ["smoke coming from the heater", "fire", "flood in the bathroom"])
async def test_us6_emergency_needs_no_llm(text: str) -> None:
    llm = FakeLlm(down=True)

    store = await triage(llm, text)

    status = store.status(CASE)
    assert (status.state, status.reason, status.safety) == (
        CaseState.HELD,
        StateReason.EMERGENCY,
        True,
    )
    assert status.urgency is Urgency.URGENT
    assert guest_status(status, GUIDANCE) == GUIDANCE
    assert [(t.kind, t.state) for t in store.tasks] == [(TaskKind.EMERGENCY, TaskState.HELD)]
    assert llm.calls == []
    assert steps(store) == ["safety:emergency"]


async def test_i9_safety_beats_spam() -> None:
    llm = FakeLlm(verdicts={"gas smell lol": Verdict.SPAM})

    store = await triage(llm, "gas smell lol")

    status = store.status(CASE)
    assert status.state is CaseState.HELD
    assert status.safety
    assert status.urgency is Urgency.URGENT
    assert llm.calls == []


async def test_i9_spam_after_safety_not_parked() -> None:
    llm = FakeLlm(verdicts={"cheap watches": Verdict.SPAM})

    store = await triage(llm, "smoke in the kitchen", "cheap watches")

    assert store.status(CASE).state is CaseState.HELD
    assert steps(store)[-1] == "park:held"


async def test_us6_safety_unparks_spam_case() -> None:
    llm = FakeLlm(verdicts={"cheap watches www.example.biz": Verdict.SPAM})

    store = await triage(llm, "cheap watches www.example.biz", "fire in cabin C12")

    status = store.status(CASE)
    assert (status.state, status.reason) == (CaseState.HELD, StateReason.EMERGENCY)


@pytest.mark.parametrize(
    "intent, category, route",
    [
        ("I want a refund for last night", Category.REFUND, Route.MONEY),
        ("can we move to a bigger cabin?", Category.CABIN_MOVE, Route.MONEY),
        ("I want a refund for last night", Category.REFUND, Route.FAULT),
        ("we deserve compensation", Category.COMPENSATION, Route.QUESTION),
    ],
    ids=["refund", "cabin-move", "refund-as-fault", "compensation-as-question"],
)
async def test_us8_money_held(intent: str, category: Category, route: Route) -> None:
    llm = FakeLlm(classes={intent: proposal(category, route, Urgency.NORMAL)})

    store = await triage(llm, intent)

    status = store.status(CASE)
    assert (status.state, status.reason) == (CaseState.HELD, StateReason.MONEY)
    assert guest_status(status, GUIDANCE) == WAITING_ON_RECEPTION
    assert [(t.kind, t.state) for t in store.tasks] == [(TaskKind.MONEY, TaskState.HELD)]


async def test_us10_spam_parked() -> None:
    text = "cheap watches www.example.biz"
    llm = FakeLlm(verdicts={text: Verdict.SPAM})

    store = await triage(llm, text)

    status = store.status(CASE)
    assert (status.state, status.reason) == (CaseState.PARKED, StateReason.SPAM)
    assert store.tasks == []
    assert llm.calls == ["verify"]
    assert steps(store) == ["safety:clear", "verify:spam", "park:parked"]


async def test_us10_parked_case_stays_parked() -> None:
    llm = FakeLlm(verdicts={"cheap watches": Verdict.SPAM})

    store = await triage(llm, "cheap watches", "where is the pool")

    assert store.status(CASE).state is CaseState.PARKED
    assert store.tasks == []
    assert steps(store)[-1] == "safety:stop_parked"


async def test_us10_nonsense_one_question() -> None:
    llm = FakeLlm(verdicts={"asdfgh": Verdict.UNCLEAR})

    store = await triage(llm, "asdfgh")

    status = store.status(CASE)
    assert (status.state, status.clarify_rounds) == (CaseState.OPEN, 1)
    assert guest_status(status, GUIDANCE) == CLARIFY
    assert store.tasks == []
    assert steps(store) == ["safety:clear", "verify:unclear", "clarify:asked"]


async def test_us2_held_after_2_rounds() -> None:
    llm = FakeLlm(verdicts={"it's broken": Verdict.UNCLEAR, "it is": Verdict.UNCLEAR})

    store = await triage(llm, "it's broken", "it is", "it is")

    status = store.status(CASE)
    assert (status.state, status.reason) == (CaseState.HELD, StateReason.CLARIFY_LIMIT)
    assert guest_status(status, GUIDANCE) == WAITING_ON_RECEPTION
    assert [s for s in steps(store) if s.startswith("clarify")] == [
        "clarify:asked",
        "clarify:asked",
        "clarify:held",
    ]


async def test_us2_clear_answer_resets_rounds() -> None:
    llm = FakeLlm(verdicts={"it's broken": Verdict.UNCLEAR})

    store = await triage(llm, "it's broken", "the heater in the lounge")

    status = store.status(CASE)
    assert (status.state, status.clarify_rounds) == (CaseState.OPEN, 0)
    assert guest_status(status, GUIDANCE) == RECEIVED


async def test_us2_two_intents_two_tasks() -> None:
    text = "No hot water, and book dinner for 2 at 19:30"
    llm = FakeLlm(
        splits={text: ["No hot water", "book dinner for 2 at 19:30"]},
        classes={"No hot water": HOT_WATER, "book dinner for 2 at 19:30": DINNER},
    )

    store = await triage(llm, text)

    assert [(t.step_id, t.kind, t.state) for t in store.tasks] == [
        ("m1/t0", TaskKind.FAULT, TaskState.QUEUED),
        ("m1/t1", TaskKind.TABLE, TaskState.QUEUED),
    ]
    assert store.status(CASE).urgency is Urgency.URGENT
    assert steps(store) == [
        "safety:clear",
        "verify:genuine",
        "split:2",
        "classify:fault",
        "route_guard:fault",
        "classify:table",
        "route_guard:table",
    ]


async def test_us2_fault_without_scope_waits() -> None:
    llm = FakeLlm(classes={"no hot water": HOT_WATER})

    store = await triage(llm, "no hot water", store=new_store(scope=None))

    assert [(t.kind, t.state) for t in store.tasks] == [(TaskKind.FAULT, TaskState.AWAITING_SCOPE)]


async def test_us3_question_needs_no_scope() -> None:
    store = await triage(FakeLlm(), "When does the pool open?", store=new_store(scope=None))

    assert [(t.kind, t.state) for t in store.tasks] == [(TaskKind.QUESTION, TaskState.QUEUED)]


async def test_us2_llm_down_held() -> None:
    llm = FakeLlm(down=True)

    store = await triage(llm, "where is the pool")

    status = store.status(CASE)
    assert (status.state, status.reason) == (CaseState.HELD, StateReason.LLM_FAILED)
    assert guest_status(status, GUIDANCE) == WITH_RECEPTION
    assert steps(store) == ["safety:clear", "llm_failed:held"]
    assert store.audit[-1].detail == {"failed_step": "verify"}


@pytest.mark.parametrize(
    "texts, expected",
    [
        (["fire"], ["safety:emergency"]),
        (["spam"], ["safety:clear", "verify:spam", "park:parked"]),
        (["spam", "hello"], ["safety:clear", "verify:spam", "park:parked", "safety:stop_parked"]),
        (["huh"], ["safety:clear", "verify:unclear", "clarify:asked"]),
        (
            ["refund"],
            [
                "safety:clear",
                "verify:genuine",
                "split:1",
                "classify:money",
                "route_guard:money",
            ],
        ),
        (
            ["pool?"],
            [
                "safety:clear",
                "verify:genuine",
                "split:1",
                "classify:question",
                "route_guard:question",
                "answer:no_section",
            ],
        ),
    ],
    ids=["safety", "verify-park", "parked", "clarify", "split-classify-guard", "answer"],
)
async def test_i13_every_node_audits(texts: list[str], expected: list[str]) -> None:
    llm = FakeLlm(
        verdicts={"spam": Verdict.SPAM, "huh": Verdict.UNCLEAR}, classes={"refund": REFUND}
    )

    store = await triage(llm, *texts)

    assert steps(store) == expected


async def test_i13_llm_failure_audited() -> None:
    store = await triage(FakeLlm(down=True), "hello")

    assert steps(store) == ["safety:clear", "llm_failed:held"]


class ParkedMidStep(InMemoryTriageStore):
    def __init__(self) -> None:
        super().__init__()
        self.add_case(CASE)
        self.raced = False

    async def commit(self, case_id: int, step: StepRecord) -> None:
        if step.status is not None and step.audit.step == "route_guard" and not self.raced:
            self.raced = True
            case = self.cases[case_id]
            self.write_status(case_id, case.change(case.status.park(StateReason.SPAM)))
        await super().commit(case_id, step)


async def test_i10_park_between_read_and_write_kept() -> None:
    llm = FakeLlm(classes={"I want a refund": REFUND})
    store = ParkedMidStep()

    await triage(llm, "I want a refund", store=store)

    status = store.status(CASE)
    assert (status.state, status.reason) == (CaseState.PARKED, StateReason.SPAM)
    assert store.raced
    assert [s for s in steps(store) if s.startswith("route_guard")] == ["route_guard:money"]

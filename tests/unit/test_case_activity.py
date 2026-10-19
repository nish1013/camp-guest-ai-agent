from dataclasses import replace

import pytest

from camp_agent.domain.case_activity import asks_guest, in_action, triages_follow_up
from camp_agent.domain.case_state import CaseState, StateReason
from camp_agent.domain.case_status import CaseStatus
from camp_agent.domain.fault_type import FaultType
from camp_agent.domain.route_guard import Category, Route, TaskState
from camp_agent.domain.urgency import Urgency
from camp_agent.llm.llm_types import Classification, Verdict
from tests.fakes import FakeLlm, InMemoryTriageStore
from tests.unit.triage_support import CASE, steps, triage

pytestmark = pytest.mark.anyio

TICKETED = [TaskState.TICKETED]
BOOKED = [TaskState.BOOKING_REQUESTED]
ACTED = {TaskState.TICKETED, TaskState.BOOKING_REQUESTED}
DINNER = Classification(category=Category.RESTAURANT, route=Route.TABLE, urgency=Urgency.NORMAL)
HOT_WATER = Classification(
    category=Category.MAINTENANCE,
    route=Route.FAULT,
    urgency=Urgency.URGENT,
    fault_type=FaultType.HOT_WATER,
)


@pytest.mark.parametrize(
    "status, states, triaged",
    [
        (CaseStatus(), [], True),
        (CaseStatus(), [TaskState.QUEUED, TaskState.HELD], True),
        (CaseStatus(), TICKETED, False),
        (CaseStatus(), BOOKED, False),
        (CaseStatus(), [TaskState.HELD, *BOOKED], False),
        (CaseStatus(clarify_rounds=1), TICKETED, True),
        (CaseStatus(), [*TICKETED, TaskState.AWAITING_SAME], True),
        (CaseStatus(), [*TICKETED, TaskState.AWAITING_SPLIT], True),
        (CaseStatus(), [*TICKETED, TaskState.AWAITING_SCOPE], True),
        (CaseStatus(), [*BOOKED, TaskState.AWAITING_SCOPE], True),
    ],
    ids=[
        "new",
        "no-ticket",
        "in-action",
        "booking-request",
        "held-and-booking",
        "clarify",
        "same",
        "split",
        "step-up",
        "booking-step-up",
    ],
)
def test_d14_follow_up_rule(status: CaseStatus, states: list[TaskState], triaged: bool) -> None:
    assert triages_follow_up(status, states) is triaged
    assert in_action(states) is not ACTED.isdisjoint(states)
    assert asks_guest(status, states) is (triaged and in_action(states))


async def test_d14_follow_up_joins_case() -> None:
    llm = FakeLlm(classes={"no hot water": HOT_WATER}, verdicts={"asdf!!!": Verdict.SPAM})
    store = await triage(llm, "no hot water")
    calls = len(llm.calls)

    await triage(llm, "asdf!!!", store=store)

    assert len(llm.calls) == calls
    assert store.status(CASE).state is CaseState.OPEN
    assert [t.state for t in store.tasks] == TICKETED
    assert steps(store)[-1] == "safety:joined"


async def test_us5_is_it_booked_joins_case() -> None:
    llm = FakeLlm(classes={"table for 4 at 19:30": DINNER})
    store = await triage(llm, "table for 4 at 19:30")
    calls = len(llm.calls)

    await triage(llm, "is it booked?", store=store)

    assert len(llm.calls) == calls
    assert [t.state for t in store.tasks] == BOOKED
    assert store.answers == []
    assert steps(store)[-1] == "safety:joined"


async def test_d14_smoke_follow_up_emergency() -> None:
    store = await triage(FakeLlm(classes={"no hot water": HOT_WATER}), "no hot water")

    await triage(FakeLlm(down=True), "now there is smoke", store=store)

    status = store.status(CASE)
    assert (status.state, status.reason, status.urgency) == (
        CaseState.HELD,
        StateReason.EMERGENCY,
        Urgency.URGENT,
    )
    assert store.tasks[0].state is TaskState.TICKETED


async def test_d14_clarify_reply_triaged() -> None:
    store = await triage(FakeLlm(classes={"no hot water": HOT_WATER}), "no hot water")
    case = store.cases[CASE]
    store.cases[CASE] = replace(case, status=replace(case.status, clarify_rounds=1))
    llm = FakeLlm()

    await triage(llm, "the lounge one", store=store)

    assert "verify" in llm.calls
    assert steps(store)[-1] != "safety:joined"


class ActedAfterEntry(InMemoryTriageStore):
    # A ticket or a booking request lands after the entry check read the task states.
    def __init__(self, acted: list[TaskState]) -> None:
        super().__init__()
        self.reads = 0
        self._acted = acted

    async def task_states(self, case_id: int) -> list[TaskState]:
        self.reads += 1
        return [] if self.reads == 1 else self._acted


@pytest.mark.parametrize("acted", [TICKETED, BOOKED], ids=["ticket", "booking-request"])
async def test_d14_park_refused_in_action(acted: list[TaskState]) -> None:
    store = ActedAfterEntry(acted)
    store.add_case(CASE)

    await triage(FakeLlm(verdicts={"cheap watches": Verdict.SPAM}), "cheap watches", store=store)

    assert store.status(CASE).state is CaseState.OPEN
    assert steps(store)[-1] == "park:refused_in_action"

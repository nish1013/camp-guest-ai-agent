from dataclasses import replace

import pytest

from camp_agent.domain.arg_validation import ValidationOutcome
from camp_agent.domain.audit_entry import AuditEntry
from camp_agent.domain.cabin_reports import ReportDraft
from camp_agent.domain.case_state import CaseState, StateReason
from camp_agent.domain.fault_type import FaultType
from camp_agent.domain.guest_status import WITH_RECEPTION, guest_status
from camp_agent.domain.route_guard import Category, Route, TaskState
from camp_agent.domain.scope import ScopeSource
from camp_agent.domain.specialist import Team
from camp_agent.domain.ticket_status import TicketStatus
from camp_agent.domain.urgency import Urgency
from camp_agent.graph.triage_types import StepRecord, TaskTransition, TicketLink
from camp_agent.llm.llm_types import Classification, TicketArgs
from tests.fakes import FakeLlm, FakeTickets, InMemoryTriageStore, oct_19
from tests.unit.triage_support import C12, CASE, RECEPTION, graph_for, new_store, steps, triage

pytestmark = pytest.mark.anyio

HEATER = "heater broken"
HOT_WATER = Classification(
    category=Category.MAINTENANCE,
    route=Route.FAULT,
    urgency=Urgency.URGENT,
    fault_type=FaultType.HOT_WATER,
)
HEATING = Classification(
    category=Category.MAINTENANCE,
    route=Route.FAULT,
    urgency=Urgency.NORMAL,
    fault_type=FaultType.HEATING,
)
TOWELS = Classification(
    category=Category.HOUSEKEEPING,
    route=Route.FAULT,
    urgency=Urgency.CAN_WAIT,
    fault_type=FaultType.SUPPLIES,
)
TWO = "heater is off and the tap leaks"
T7 = TicketLink("T7", TicketStatus.OPEN, 1, "C12")
ANSWERED = AuditEntry("answer", "yes")


def c14(summary: str = HEATER) -> TicketArgs:
    return TicketArgs(tool="create_ticket", cabin="C14", summary=summary)


def earlier_heating(store: InMemoryTriageStore, ticket: TicketLink | None = T7) -> int:
    draft = ReportDraft("C12", FaultType.HEATING, "m0/t0", "bedroom heater", oct_19().now())
    return store.add_report(draft, ticket)


def states(store: InMemoryTriageStore) -> list[TaskState]:
    return [task.state for task in store.tasks]


def outcomes(store: InMemoryTriageStore) -> list[ValidationOutcome]:
    return [record.outcome for record in store.validations]


async def answer(store: InMemoryTriageStore, step_id: str, state: TaskState) -> None:
    task = next(task for task in store.tasks if task.step_id == step_id)
    move = TaskTransition(step_id, state, task.state)
    await store.commit(CASE, StepRecord(ANSWERED, transitions=(move,)))


async def test_us4_hot_water_ticket() -> None:
    tickets = FakeTickets()

    store = await triage(
        FakeLlm(classes={"no hot water": HOT_WATER}), "no hot water", tickets=tickets
    )

    [request] = tickets.created.values()
    assert (request.cabin, request.team, request.urgency, request.fault_type) == (
        "C12",
        Team.MAINTENANCE,
        Urgency.URGENT,
        FaultType.HOT_WATER,
    )
    assert (request.key.case_id, request.key.step_id) == (CASE, "m1/t0")
    assert states(store) == [TaskState.TICKETED]
    assert store.tickets["m1/t0"].ref == "T1"
    assert outcomes(store) == [ValidationOutcome.PASS]


async def test_us4_towels_to_housekeeping() -> None:
    tickets = FakeTickets()

    await triage(FakeLlm(classes={"extra towels": TOWELS}), "extra towels", tickets=tickets)

    [request] = tickets.created.values()
    assert (request.team, request.urgency) == (Team.HOUSEKEEPING, Urgency.CAN_WAIT)


async def test_d39_two_faults_wait_for_yes() -> None:
    llm = FakeLlm(
        splits={TWO: ["heater is off", "the tap leaks"]},
        classes={"heater is off": HEATING, "the tap leaks": HEATING},
    )
    tickets = FakeTickets()

    store = await triage(llm, TWO, tickets=tickets)

    assert states(store) == [TaskState.AWAITING_SPLIT] * 2
    assert tickets.calls == 0
    assert steps(store)[-1] == "confirm_split:asked"


async def test_d39_split_yes_two_tickets() -> None:
    llm = FakeLlm(
        splits={TWO: ["heater is off", "the tap leaks"]},
        classes={"heater is off": HEATING, "the tap leaks": HEATING},
    )
    tickets = FakeTickets()
    store = await triage(llm, TWO, tickets=tickets)
    for step_id in ("m1/t0", "m1/t1"):
        await answer(store, step_id, TaskState.SPLIT_CONFIRMED)

    await graph_for(llm, store, tickets=tickets).resume(CASE)

    assert states(store) == [TaskState.TICKETED] * 2
    assert len(tickets.created) == 2


async def test_d39_urgent_fault_skips_split() -> None:
    text = "no hot water and the tap leaks"
    llm = FakeLlm(
        splits={text: ["no hot water", "the tap leaks"]},
        classes={"no hot water": HOT_WATER, "the tap leaks": HEATING},
    )
    tickets = FakeTickets()

    store = await triage(llm, text, tickets=tickets)

    assert states(store) == [TaskState.TICKETED] * 2
    assert "confirm_split:asked" not in steps(store)


async def test_i6_blocked_args_no_ticket() -> None:
    llm = FakeLlm(classes={HEATER: HEATING}, drafts={HEATER: [c14(), c14()]})
    tickets = FakeTickets()

    store = await triage(llm, HEATER, tickets=tickets)

    assert tickets.calls == 0
    assert store.tickets == {}
    assert outcomes(store) == [ValidationOutcome.BLOCK, ValidationOutcome.BLOCK]
    assert states(store) == [TaskState.HELD]
    status = store.status(CASE)
    assert (status.state, status.reason) == (CaseState.HELD, StateReason.FAULT_REVIEW)
    assert steps(store)[-2:] == ["validate:block", "validate:held"]


async def test_d15_one_reprompt_then_ticket() -> None:
    llm = FakeLlm(classes={HEATER: HEATING}, drafts={HEATER: [c14()]})
    tickets = FakeTickets()

    store = await triage(llm, HEATER, tickets=tickets)

    assert [brief.rejected_for for brief in llm.briefs] == [(), ("cabin must be C12",)]
    assert outcomes(store) == [ValidationOutcome.BLOCK, ValidationOutcome.PASS]
    [request] = tickets.created.values()
    assert request.cabin == "C12"
    assert states(store) == [TaskState.TICKETED]


async def test_d38_maybe_same_asks_guest() -> None:
    store = new_store()
    earlier = earlier_heating(store)
    llm = FakeLlm(classes={HEATER: HEATING}, same={HEATER: earlier})
    tickets = FakeTickets()

    store = await triage(llm, HEATER, store=store, tickets=tickets)

    assert states(store) == [TaskState.AWAITING_SAME]
    assert store.same == {"m1/t0": earlier}
    assert tickets.calls == 0
    assert store.audit[-1].detail == {
        "step_id": "m1/t0",
        "report": 2,
        "checked_against": [str(earlier)],
        "maybe": earlier,
    }


async def test_d38_same_yes_links_ticket() -> None:
    store = new_store()
    earlier = earlier_heating(store)
    llm = FakeLlm(classes={HEATER: HEATING}, same={HEATER: earlier})
    tickets = FakeTickets()
    store = await triage(llm, HEATER, store=store, tickets=tickets)
    await answer(store, "m1/t0", TaskState.LINKING)

    await graph_for(llm, store, tickets=tickets).resume(CASE)

    assert states(store) == [TaskState.TICKETED]
    assert store.tickets["m1/t0"] == T7
    assert tickets.calls == 0
    assert outcomes(store) == [ValidationOutcome.PASS]
    assert steps(store)[-1] == "link:linked"


async def test_d38_same_no_new_ticket() -> None:
    store = new_store()
    earlier = earlier_heating(store)
    llm = FakeLlm(classes={HEATER: HEATING}, same={HEATER: earlier})
    tickets = FakeTickets()
    store = await triage(llm, HEATER, store=store, tickets=tickets)
    await answer(store, "m1/t0", TaskState.DRAFTING)

    await graph_for(llm, store, tickets=tickets).resume(CASE)

    assert states(store) == [TaskState.TICKETED]
    assert store.tickets["m1/t0"].ref == "T1"
    assert llm.calls.count("same_problem") == 1


async def test_d38_link_without_ticket_held() -> None:
    store = new_store()
    earlier = earlier_heating(store, ticket=None)
    llm = FakeLlm(classes={HEATER: HEATING}, same={HEATER: earlier})
    tickets = FakeTickets()
    store = await triage(llm, HEATER, store=store, tickets=tickets)
    await answer(store, "m1/t0", TaskState.LINKING)

    await graph_for(llm, store, tickets=tickets).resume(CASE)

    assert states(store) == [TaskState.HELD]
    assert store.status(CASE).reason is StateReason.FAULT_REVIEW
    assert tickets.calls == 0


@pytest.mark.parametrize("proposed", [None, 99], ids=["different", "not-offered"])
async def test_d38_different_new_ticket(proposed: int | None) -> None:
    store = new_store()
    earlier_heating(store)
    same = {} if proposed is None else {HEATER: proposed}
    llm = FakeLlm(classes={HEATER: HEATING}, same=same)

    store = await triage(llm, HEATER, store=store)

    assert states(store) == [TaskState.TICKETED]
    assert "same:different" in steps(store)


async def test_d43_ticketing_down_held() -> None:
    tickets = FakeTickets()
    tickets.down = True

    store = await triage(FakeLlm(classes={HEATER: HEATING}), HEATER, tickets=tickets)

    assert states(store) == [TaskState.HELD]
    status = store.status(CASE)
    assert status.reason is StateReason.TICKETING_DOWN
    assert guest_status(status, "", RECEPTION) == WITH_RECEPTION


@pytest.mark.parametrize("step", ["same_problem", "draft_ticket"])
async def test_d16_fault_llm_down_holds_task(step: str) -> None:
    store = new_store()
    earlier_heating(store)
    llm = FakeLlm(classes={HEATER: HEATING})
    llm.down_for.add(step)

    store = await triage(llm, HEATER, store=store)

    assert states(store) == [TaskState.HELD]
    assert store.status(CASE).reason is StateReason.LLM_FAILED


async def test_us4_fault_with_no_specialist_held() -> None:
    other = Classification(category=Category.OTHER, route=Route.FAULT, urgency=Urgency.NORMAL)
    tickets = FakeTickets()

    store = await triage(FakeLlm(classes={"the door": other}), "the door", tickets=tickets)

    assert states(store) == [TaskState.HELD]
    assert tickets.calls == 0
    assert steps(store)[-1] == "validate:no_specialist"


async def test_i13_fault_steps_audited() -> None:
    store = new_store()
    earlier_heating(store)

    store = await triage(FakeLlm(classes={HEATER: HEATING}), HEATER, store=store)

    assert steps(store) == [
        "safety:clear",
        "verify:genuine",
        "split:1",
        "classify:fault",
        "route_guard:fault",
        "same:different",
        "ticket:created",
    ]


async def test_d39_split_asked_after_step_up() -> None:
    llm = FakeLlm(
        splits={TWO: ["heater is off", "the tap leaks"]},
        classes={"heater is off": HEATING, "the tap leaks": HEATING},
    )
    store = await triage(llm, TWO, store=new_store(scope=None))
    store.cases[CASE] = replace(store.cases[CASE], scope=replace(C12, source=ScopeSource.STEP_UP))

    await graph_for(llm, store).resume(CASE)

    assert states(store) == [TaskState.AWAITING_SPLIT] * 2
    assert steps(store)[-1] == "confirm_split:asked"

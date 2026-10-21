from dataclasses import replace
from datetime import date, time

import pytest

from camp_agent.domain.arg_validation import ValidationOutcome
from camp_agent.domain.cases import CaseState, StateReason
from camp_agent.domain.guest_status import RECEIVED, WAITING_ON_RECEPTION, guest_status
from camp_agent.domain.routing import (
    Category,
    Route,
    Scope,
    ScopeSource,
    TaskKind,
    TaskState,
    Urgency,
)
from camp_agent.domain.table_bookings import TableBooking
from camp_agent.llm.port import GuideAnswer, TableArgs, TableBrief
from tests.fakes import FakeLlm, InMemoryTriageStore, table_args
from tests.unit.triage_support import (
    C12,
    CASE,
    RECEPTION,
    graph_for,
    new_store,
    proposal,
    steps,
    triage,
)

pytestmark = pytest.mark.anyio

TABLE = "table for 4 at 19:30 tonight"
DINNER = proposal(Category.RESTAURANT, Route.TABLE, Urgency.NORMAL)
ENDED = Scope("C12", date(2026, 10, 10), date(2026, 10, 17), ScopeSource.QR)
PHONE = "Call 01632 960124 to ask about a table."


def booking_llm(*drafts: TableArgs) -> FakeLlm:
    return FakeLlm(classes={TABLE: DINNER}, tables={TABLE: list(drafts)} if drafts else None)


def states(store: InMemoryTriageStore) -> list[TaskState]:
    return [task.state for task in store.tasks]


def outcomes(store: InMemoryTriageStore) -> list[ValidationOutcome]:
    return [record.outcome for record in store.validations]


async def test_us5_table_booking_requested() -> None:
    llm = booking_llm()

    store = await triage(llm, TABLE)

    assert states(store) == [TaskState.BOOKING_REQUESTED]
    assert store.bookings == {"m1/t0": TableBooking("C12", 4, date(2026, 10, 19), time(19, 30))}
    assert outcomes(store) == [ValidationOutcome.PASS]
    assert llm.table_briefs == [
        TableBrief(TABLE, "C12", date(2026, 10, 19), date(2026, 10, 18), date(2026, 10, 25))
    ]
    assert steps(store)[-2:] == ["route_guard:table", "booking:requested"]
    assert store.audit[-1].detail == {"step_id": "m1/t0", "party": 4, "at": "2026-10-19 19:30"}


async def test_d12_request_is_not_booked() -> None:
    store = await triage(booking_llm(), TABLE)

    status = store.status(CASE)
    assert status.state is CaseState.OPEN
    assert guest_status(status, "", RECEPTION) == RECEIVED


async def test_d15_table_one_reprompt() -> None:
    llm = booking_llm(table_args(cabin="C14"))

    store = await triage(llm, TABLE)

    assert [brief.rejected_for for brief in llm.table_briefs] == [(), ("cabin must be C12",)]
    assert outcomes(store) == [ValidationOutcome.BLOCK, ValidationOutcome.PASS]
    assert store.bookings["m1/t0"].cabin == "C12"


async def test_i6_blocked_table_no_request() -> None:
    llm = booking_llm(table_args(party=None), table_args(party=None))

    store = await triage(llm, TABLE)

    assert store.bookings == {}
    assert outcomes(store) == [ValidationOutcome.BLOCK, ValidationOutcome.BLOCK]
    assert states(store) == [TaskState.HELD]
    status = store.status(CASE)
    assert (status.state, status.reason) == (CaseState.HELD, StateReason.BOOKING_REVIEW)
    assert guest_status(status, "", RECEPTION) == WAITING_ON_RECEPTION
    assert steps(store)[-2:] == ["validate:block", "validate:held"]


async def test_d16_table_llm_down_held() -> None:
    llm = booking_llm()
    llm.down_for.add("draft_table")

    store = await triage(llm, TABLE)

    assert states(store) == [TaskState.HELD]
    status = store.status(CASE)
    assert (status.state, status.reason) == (CaseState.HELD, StateReason.LLM_FAILED)
    assert steps(store)[-1] == "restaurant:held"


async def test_us5_no_scope_waits_then_books() -> None:
    llm = booking_llm()
    store = await triage(llm, TABLE, store=new_store(scope=None))

    assert [(t.kind, t.state) for t in store.tasks] == [(TaskKind.TABLE, TaskState.AWAITING_SCOPE)]
    assert "draft_table" not in llm.calls

    store.cases[CASE] = replace(store.cases[CASE], scope=replace(C12, source=ScopeSource.STEP_UP))
    await graph_for(llm, store).resume(CASE)

    assert states(store) == [TaskState.BOOKING_REQUESTED]


async def test_d19_ended_stay_guide_answer() -> None:
    llm = FakeLlm(
        classes={TABLE: DINNER}, answers={TABLE: GuideAnswer(text=PHONE, section_id="restaurant")}
    )

    store = await triage(llm, TABLE, store=new_store(scope=ENDED))

    assert [t.kind for t in store.tasks] == [TaskKind.QUESTION]
    assert [(a.text, a.section_id) for a in store.answers] == [(PHONE, "restaurant")]
    assert "draft_table" not in llm.calls
    assert store.bookings == {}


class ParkedDuringDraft(FakeLlm):
    # A park commits while the restaurant args are drafted.
    def __init__(self, store: InMemoryTriageStore) -> None:
        super().__init__(classes={TABLE: DINNER})
        self._store = store

    async def draft_table(self, brief: TableBrief) -> TableArgs:
        case = self._store.cases[CASE]
        self._store.write_status(CASE, case.change(case.status.park(StateReason.SPAM)))
        return await super().draft_table(brief)


async def test_i8_park_during_draft_no_request() -> None:
    store = new_store()

    await triage(ParkedDuringDraft(store), TABLE, store=store)

    assert store.status(CASE).state is CaseState.PARKED
    assert store.bookings == {}
    assert states(store) == [TaskState.QUEUED]
    assert steps(store)[-1] == "booking:stopped_parked"

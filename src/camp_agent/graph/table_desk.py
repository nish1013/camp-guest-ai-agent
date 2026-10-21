from langgraph.graph import END

from camp_agent.clock import Clock
from camp_agent.domain.arg_validation import check_table_args
from camp_agent.domain.cases import AuditEntry, AuditValue, CaseState, StateReason
from camp_agent.domain.routing import TaskState
from camp_agent.domain.table_bookings import TableTask, next_to_book
from camp_agent.graph.triage import (
    BOOKING,
    DISPATCH,
    CaseSnapshot,
    StepRecord,
    TaskHold,
    TaskTransition,
    TriagePolicy,
    TriageState,
    TriageStore,
    TriageUpdate,
    ValidationRecord,
    hold_task,
    required_scope,
)
from camp_agent.llm.port import LlmError, LlmPort, TableBrief

VALIDATE = "validate"
RESTAURANT = "restaurant"
# One draft and one reprompt, then a person decides (D15).
_MAX_DRAFTS = 2


class TableDesk:
    def __init__(
        self, llm: LlmPort, store: TriageStore, clock: Clock, policy: TriagePolicy
    ) -> None:
        self._llm = llm
        self._store = store
        self._clock = clock
        self._policy = policy

    async def next_step(self, case_id: int) -> TriageUpdate | None:
        table = next_to_book(await self._store.tables(case_id))
        if table is None:
            return None
        return {"next": BOOKING, "table": table.step_id, "drafts": 0, "rejected_for": []}

    # Specialists draft only: the request waits for staff to confirm (D12).
    async def book(self, state: TriageState) -> TriageUpdate:
        case = await self._store.load(state["case_id"])
        table = await self._table(state)
        detail: dict[str, AuditValue] = {"step_id": table.step_id}
        if case.status.state is CaseState.PARKED:
            await self._audit(state, AuditEntry(BOOKING, "stopped_parked", detail))
            return {"next": END}
        scope = required_scope(case)
        brief = TableBrief(
            table.summary,
            scope.cabin,
            self._clock.today(),
            scope.stay_from,
            scope.stay_to,
            tuple(state["rejected_for"]),
        )
        try:
            args = await self._llm.draft_table(brief)
        except LlmError:
            audit = AuditEntry(RESTAURANT, "held", detail)
            return await self._hold(state, table, StateReason.LLM_FAILED, audit, case)
        now = self._clock.now().astimezone(self._policy.camp_timezone)
        check = check_table_args(
            args.tool, args.cabin, args.party, args.date, args.time, scope, now
        )
        record = ValidationRecord(table.step_id, check.outcome, args.model_dump(mode="json"))
        booking = check.booking
        # Only a passing record becomes a booking request (I6).
        if booking is None:
            drafts = state["drafts"] + 1
            detail["reasons"] = list(check.reasons)
            if drafts < _MAX_DRAFTS:
                await self._commit(state, AuditEntry(VALIDATE, "block", detail), record)
                return {"next": BOOKING, "drafts": drafts, "rejected_for": list(check.reasons)}
            audit = AuditEntry(VALIDATE, "held", detail)
            return await self._hold(state, table, StateReason.BOOKING_REVIEW, audit, case, record)
        detail |= {"party": booking.party, "at": f"{booking.day} {booking.at:%H:%M}"}
        move = TaskTransition(
            table.step_id, TaskState.BOOKING_REQUESTED, table.state, booking=booking
        )
        # A park waits for this commit, then loses the version check; one that committed first
        # is seen here (I8).
        async with self._store.lock_case(state["case_id"]) as locked:
            if locked.case.status.state is CaseState.PARKED:
                await locked.commit(StepRecord(AuditEntry(BOOKING, "stopped_parked", detail)))
                return {"next": END}
            step = StepRecord(
                AuditEntry(BOOKING, "requested", detail),
                locked.case.change(locked.case.status),
                transitions=(move,),
                validation=record,
            )
            await locked.commit(step)
        return {"next": DISPATCH}

    async def _hold(
        self,
        state: TriageState,
        table: TableTask,
        reason: StateReason,
        audit: AuditEntry,
        case: CaseSnapshot,
        record: ValidationRecord | None = None,
    ) -> TriageUpdate:
        hold = TaskHold(table.step_id, table.state, reason, audit, record)
        await hold_task(self._store, state["case_id"], hold, self._clock.now(), case)
        return {"next": DISPATCH}

    async def _commit(
        self, state: TriageState, audit: AuditEntry, record: ValidationRecord
    ) -> None:
        await self._store.commit(state["case_id"], StepRecord(audit, validation=record))

    async def _audit(self, state: TriageState, audit: AuditEntry) -> None:
        await self._store.commit(state["case_id"], StepRecord(audit))

    async def _table(self, state: TriageState) -> TableTask:
        for table in await self._store.tables(state["case_id"]):
            if table.step_id == state["table"]:
                return table
        raise RuntimeError(f"no table task {state['table']}")

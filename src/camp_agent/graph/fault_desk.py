from langgraph.graph import END

from camp_agent.clock import Clock
from camp_agent.domain.arg_validation import (
    LinkDecision,
    ValidationOutcome,
    check_link,
    check_ticket_args,
)
from camp_agent.domain.audit_entry import AuditEntry, AuditValue
from camp_agent.domain.cabin_reports import ReportDraft
from camp_agent.domain.case_state import CaseState, StateReason
from camp_agent.domain.fault_flow import FaultTask, next_actionable, split_to_confirm
from camp_agent.domain.route_guard import TaskState
from camp_agent.domain.scope import Scope
from camp_agent.domain.specialist import specialist_for
from camp_agent.graph.triage_state import (
    CONFIRM_SPLIT,
    LINK,
    REPORT,
    SAME,
    SPECIALIST,
    TriageState,
    TriageUpdate,
)
from camp_agent.graph.triage_store import TriageStore
from camp_agent.graph.triage_types import (
    CaseSnapshot,
    StepRecord,
    TaskTransition,
    TicketLink,
    ValidationRecord,
)
from camp_agent.llm.llm_error import LlmError
from camp_agent.llm.llm_port import LlmPort
from camp_agent.llm.llm_types import TicketBrief
from camp_agent.ticket.ticket_error import TicketError
from camp_agent.ticket.ticket_port import TicketPort
from camp_agent.ticket.ticket_types import TicketKey, TicketReceipt, TicketRequest

VALIDATE = "validate"
TICKET = "ticket"
# One draft and one reprompt, then a person decides (D15).
_MAX_DRAFTS = 2
_STEP_FOR = {
    TaskState.QUEUED: REPORT,
    TaskState.SPLIT_CONFIRMED: REPORT,
    TaskState.DRAFTING: SPECIALIST,
    TaskState.LINKING: LINK,
}


class FaultDesk:
    def __init__(self, llm: LlmPort, store: TriageStore, tickets: TicketPort, clock: Clock) -> None:
        self._llm = llm
        self._store = store
        self._tickets = tickets
        self._clock = clock

    async def route(self, case_id: int) -> TriageUpdate:
        case = await self._store.load(case_id)
        if case.status.state is CaseState.PARKED:
            return {"next": END}
        faults = await self._store.faults(case_id)
        if split_to_confirm(faults):
            return {"next": CONFIRM_SPLIT}
        fault = next_actionable(faults)
        if fault is None:
            return {"next": END}
        return {
            "next": _STEP_FOR[fault.state],
            "fault": fault.step_id,
            "drafts": 0,
            "rejected_for": [],
            "report": None,
        }

    async def confirm_split(self, state: TriageState) -> TriageUpdate:
        case_id = state["case_id"]
        for group in split_to_confirm(await self._store.faults(case_id)):
            steps = [fault.step_id for fault in group]
            moves = tuple(
                TaskTransition(step, TaskState.AWAITING_SPLIT, TaskState.QUEUED) for step in steps
            )
            audit = AuditEntry(CONFIRM_SPLIT, "asked", {"step_ids": steps})
            await self._store.commit(case_id, StepRecord(audit, transitions=moves))
        return await self.route(case_id)

    async def report(self, state: TriageState) -> TriageUpdate:
        fault = await self._fault(state)
        scope = _scope(await self._store.load(state["case_id"]))
        draft = ReportDraft(
            scope.cabin, fault.fault_type, fault.step_id, fault.summary, self._clock.now()
        )
        saved = await self._store.save_report(state["case_id"], draft)
        return {"next": SAME, "report": saved}

    async def same(self, state: TriageState) -> TriageUpdate:
        saved = state["report"]
        if saved is None:
            raise RuntimeError("same ran without a saved report")
        fault = await self._fault(state)
        detail: dict[str, AuditValue] = {
            "step_id": fault.step_id,
            "report": saved.id,
            "checked_against": [str(report.id) for report in saved.checked_against],
        }
        if not saved.checked_against:
            await self._audit(state, AuditEntry(SAME, "none", detail))
            return {"next": SPECIALIST}
        try:
            proposed = await self._llm.same_problem(fault.summary, saved.checked_against)
        except LlmError:
            return await self._hold(state, fault, StateReason.LLM_FAILED, AuditEntry(SAME, "held"))
        offered = {report.id for report in saved.checked_against}
        if proposed.report_id not in offered:
            await self._audit(state, AuditEntry(SAME, "different", detail))
            return {"next": SPECIALIST}
        detail["maybe"] = proposed.report_id
        move = TaskTransition(
            fault.step_id, TaskState.AWAITING_SAME, fault.state, same_report_id=proposed.report_id
        )
        await self._commit(state, AuditEntry(SAME, "maybe", detail), transitions=(move,))
        return await self.route(state["case_id"])

    async def specialist(self, state: TriageState) -> TriageUpdate:
        case = await self._store.load(state["case_id"])
        fault = await self._fault(state)
        detail: dict[str, AuditValue] = {"step_id": fault.step_id}
        if case.status.state is CaseState.PARKED:
            await self._audit(state, AuditEntry(TICKET, "stopped_parked", detail))
            return {"next": END}
        scope = _scope(case)
        team = specialist_for(fault.category)
        if team is None:
            audit = AuditEntry(VALIDATE, "no_specialist", detail)
            return await self._hold(state, fault, StateReason.FAULT_REVIEW, audit, case)
        brief = TicketBrief(fault.summary, scope.cabin, tuple(state["rejected_for"]))
        try:
            args = await self._llm.draft_ticket(team, brief)
        except LlmError:
            audit = AuditEntry(SPECIALIST, "held", detail)
            return await self._hold(state, fault, StateReason.LLM_FAILED, audit, case)
        check = check_ticket_args(args.tool, args.cabin, args.summary, scope.cabin)
        record = ValidationRecord(fault.step_id, check.outcome, args.model_dump())
        # Only a passing record reaches the ticket system (I6).
        if check.outcome is ValidationOutcome.BLOCK:
            drafts = state["drafts"] + 1
            detail["reasons"] = list(check.reasons)
            if drafts < _MAX_DRAFTS:
                await self._commit(state, AuditEntry(VALIDATE, "block", detail), validation=record)
                return {"next": SPECIALIST, "drafts": drafts, "rejected_for": list(check.reasons)}
            audit = AuditEntry(VALIDATE, "held", detail)
            return await self._hold(state, fault, StateReason.FAULT_REVIEW, audit, case, record)
        request = TicketRequest(
            TicketKey(state["case_id"], fault.step_id),
            scope.cabin,
            team,
            fault.fault_type,
            fault.urgency,
            args.summary,
        )
        # A park waits for this commit or is seen here before the ticket exists (I8).
        async with self._store.lock_case(state["case_id"]) as locked:
            if locked.case.status.state is CaseState.PARKED:
                await locked.commit(StepRecord(AuditEntry(TICKET, "stopped_parked", detail)))
                return {"next": END}
            try:
                receipt: TicketReceipt | None = await self._tickets.create(request)
            except TicketError:
                receipt = None
            if receipt is not None:
                link = TicketLink(receipt.ref, receipt.status, receipt.version, scope.cabin)
                detail |= {"ticket": receipt.ref, "team": team}
                move = TaskTransition(fault.step_id, TaskState.TICKETED, fault.state, ticket=link)
                step = StepRecord(
                    AuditEntry(TICKET, "created", detail),
                    locked.case.change(locked.case.status),
                    transitions=(move,),
                    validation=record,
                )
                await locked.commit(step)
        # Outside the lock: the hold writes the case row from a connection of its own.
        if receipt is None:
            audit = AuditEntry(TICKET, "held", detail)
            return await self._hold(state, fault, StateReason.TICKETING_DOWN, audit, None, record)
        return await self.route(state["case_id"])

    async def link(self, state: TriageState) -> TriageUpdate:
        case = await self._store.load(state["case_id"])
        fault = await self._fault(state)
        detail: dict[str, AuditValue] = {"step_id": fault.step_id}
        if case.status.state is CaseState.PARKED:
            await self._audit(state, AuditEntry(TICKET, "stopped_parked", detail))
            return {"next": END}
        if fault.same_report_id is None:
            raise RuntimeError("link ran without a report to link to")
        scope = _scope(case)
        target = await self._store.link_target(fault.same_report_id)
        if target is None:
            raise RuntimeError("the report to link to does not exist")
        check = check_link(target.ticket_ref, target.ticket_status, target.cabin, scope.cabin)
        detail["report"] = fault.same_report_id
        if check.decision is LinkDecision.NEW_TICKET:
            move = TaskTransition(fault.step_id, TaskState.DRAFTING, fault.state)
            await self._commit(state, AuditEntry(LINK, "new_ticket", detail), transitions=(move,))
            return await self.route(state["case_id"])
        args = {"link": target.ticket_ref or "", "cabin": target.cabin or ""}
        if check.decision is LinkDecision.HOLD:
            record = ValidationRecord(fault.step_id, ValidationOutcome.BLOCK, args)
            detail["reasons"] = list(check.reasons)
            audit = AuditEntry(LINK, "held", detail)
            return await self._hold(state, fault, StateReason.FAULT_REVIEW, audit, case, record)
        if target.ticket_ref is None or target.ticket_status is None:
            raise RuntimeError("a link passed without a ticket")
        record = ValidationRecord(fault.step_id, ValidationOutcome.PASS, args)
        version = target.ticket_version or 0
        ticket = TicketLink(target.ticket_ref, target.ticket_status, version, scope.cabin)
        detail["ticket"] = ticket.ref
        move = TaskTransition(fault.step_id, TaskState.TICKETED, fault.state, ticket=ticket)
        await self._commit(
            state, AuditEntry(LINK, "linked", detail), case, transitions=(move,), validation=record
        )
        return await self.route(state["case_id"])

    async def _hold(
        self,
        state: TriageState,
        fault: FaultTask,
        reason: StateReason,
        audit: AuditEntry,
        case: CaseSnapshot | None = None,
        record: ValidationRecord | None = None,
    ) -> TriageUpdate:
        # The task leaves the actionable states, so no later run retries it on its own.
        case = case or await self._store.load(state["case_id"])
        status = case.status.hold(reason, self._clock.now())
        move = TaskTransition(fault.step_id, TaskState.HELD, fault.state)
        step = StepRecord(audit, case.change(status), transitions=(move,), validation=record)
        await self._store.commit(state["case_id"], step)
        return await self.route(state["case_id"])

    async def _commit(
        self,
        state: TriageState,
        audit: AuditEntry,
        case: CaseSnapshot | None = None,
        transitions: tuple[TaskTransition, ...] = (),
        validation: ValidationRecord | None = None,
    ) -> None:
        status = None if case is None else case.change(case.status)
        step = StepRecord(audit, status, transitions=transitions, validation=validation)
        await self._store.commit(state["case_id"], step)

    async def _audit(self, state: TriageState, audit: AuditEntry) -> None:
        await self._store.commit(state["case_id"], StepRecord(audit))

    async def _fault(self, state: TriageState) -> FaultTask:
        for fault in await self._store.faults(state["case_id"]):
            if fault.step_id == state["fault"]:
                return fault
        raise RuntimeError(f"no fault task {state['fault']}")


def _scope(case: CaseSnapshot) -> Scope:
    # A fault reaches the desk only once the route guard saw a scope (D19).
    if case.scope is None:
        raise RuntimeError("a fault task without a scope reached the fault desk")
    return case.scope

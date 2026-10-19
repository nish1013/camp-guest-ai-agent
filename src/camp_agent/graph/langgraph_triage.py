from typing import Any, cast

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import RetryPolicy

from camp_agent.clock import Clock
from camp_agent.domain.audit_entry import AuditEntry, AuditValue
from camp_agent.domain.case_activity import in_action, triages_follow_up
from camp_agent.domain.case_state import CaseState, StateReason
from camp_agent.domain.fault_type import FaultType
from camp_agent.domain.route_guard import Route, TaskKind, TaskState, guard_route
from camp_agent.domain.step_up import resumes_waiting
from camp_agent.domain.urgency import Urgency
from camp_agent.graph.fault_desk import FaultDesk
from camp_agent.graph.guide_answerer import GuideAnswerer
from camp_agent.graph.stale_case_error import StaleCaseError
from camp_agent.graph.table_desk import TableDesk
from camp_agent.graph.triage_graph import BatchOutcome, PendingMessage
from camp_agent.graph.triage_state import (
    ANSWER,
    BOOKING,
    CLARIFY,
    CLASSIFY,
    CONFIRM_SPLIT,
    DISPATCH,
    LINK,
    LLM_FAILED,
    PARK,
    REPORT,
    ROUTE_GUARD,
    SAFETY,
    SAME,
    SPECIALIST,
    SPLIT,
    VERIFY,
    TriageState,
    TriageUpdate,
    start_state,
)
from camp_agent.graph.triage_store import TriageStore
from camp_agent.graph.triage_types import (
    StatusChange,
    StepRecord,
    TaskAnswer,
    TaskDraft,
    TaskTransition,
    TriagePolicy,
    WaitingTask,
)
from camp_agent.llm.llm_error import LlmError
from camp_agent.llm.llm_port import LlmPort
from camp_agent.llm.llm_types import Verdict
from camp_agent.ticket.ticket_port import TicketPort

_AFTER_VERDICT = {Verdict.GENUINE: SPLIT, Verdict.SPAM: PARK, Verdict.UNCLEAR: CLARIFY}
_RECURSION_LIMIT = 1000
# A step-up or staff action changed the case between a node's read and its write: read again.
_STALE_RETRY = RetryPolicy(initial_interval=0.01, max_attempts=5, retry_on=StaleCaseError)


class LangGraphTriage:
    def __init__(
        self,
        llm: LlmPort,
        store: TriageStore,
        clock: Clock,
        policy: TriagePolicy,
        answerer: GuideAnswerer,
        tickets: TicketPort,
    ) -> None:
        self._llm = llm
        self._store = store
        self._clock = clock
        self._policy = policy
        self._answerer = answerer
        self._faults = FaultDesk(llm, store, tickets, clock)
        self._tables = TableDesk(llm, store, clock, policy)
        self._graph = self._build()

    async def run(self, case_id: int, batch: list[PendingMessage]) -> BatchOutcome:
        text = "\n".join(message.text for message in batch)
        restored = any(message.restored for message in batch)
        pick = next((message.pick for message in batch if message.pick is not None), None)
        final = await self._invoke(
            start_state(case_id, f"m{batch[0].id}", text, SAFETY, restored, pick)
        )
        return BatchOutcome.PARKED if final["parked"] else BatchOutcome.TRIAGED

    async def resume(self, case_id: int) -> None:
        moved = await self._resume_waiting(case_id)
        if (await self._next_task(case_id))["next"] != END:
            await self._invoke(start_state(case_id, "", "", DISPATCH))
        elif moved:
            await self._store.close_if_done(case_id, self._clock.now())

    async def _invoke(self, start: TriageState) -> TriageState:
        final = await self._graph.ainvoke(start, {"recursion_limit": _RECURSION_LIMIT})
        return cast(TriageState, final)

    async def _resume_waiting(self, case_id: int) -> bool:
        case = await self._store.load(case_id)
        if case.scope is None or not resumes_waiting(case.status, case.scope):
            return False
        waiting = await self._store.awaiting_scope(case_id)
        for task in waiting:
            decision = guard_route(
                task.category,
                Route(task.kind.value),
                case.scope,
                self._clock.today(),
                self._policy.held_categories,
            )
            detail: dict[str, AuditValue] = {
                "step_id": task.step_id,
                "state": decision.state,
                "scope": case.scope.source,
            }
            audit = AuditEntry(ROUTE_GUARD, decision.kind, detail)
            if decision.kind is not task.kind:
                await self._answer_waiting(case_id, task, audit)
                continue
            move = TaskTransition(task.step_id, decision.state, TaskState.AWAITING_SCOPE)
            await self._store.commit(case_id, StepRecord(audit, transitions=(move,)))
        return bool(waiting)

    async def _answer_waiting(self, case_id: int, task: WaitingTask, routed: AuditEntry) -> None:
        # The stay is not active, so the request gets a guide answer only (D19).
        await self._store.commit(case_id, StepRecord(routed))
        try:
            checked = await self._answerer.answer(task.summary)
        except LlmError:
            case = await self._store.load(case_id)
            status = case.status.hold(StateReason.LLM_FAILED, self._clock.now())
            move = TaskTransition(
                task.step_id, TaskState.HELD, TaskState.AWAITING_SCOPE, kind=TaskKind.QUESTION
            )
            audit = AuditEntry(LLM_FAILED, status.state, {"failed_step": ANSWER})
            await self._store.commit(
                case_id, StepRecord(audit, case.change(status), transitions=(move,))
            )
            return
        detail: dict[str, AuditValue] = {"step_id": task.step_id}
        if checked.proposed is not None:
            detail["proposed"] = checked.proposed
        move = TaskTransition(
            task.step_id, TaskState.QUEUED, TaskState.AWAITING_SCOPE, kind=TaskKind.QUESTION
        )
        answer = TaskAnswer(task.step_id, checked.text, checked.cited)
        audit = AuditEntry(ANSWER, checked.outcome, detail)
        await self._store.commit(case_id, StepRecord(audit, transitions=(move,), answers=(answer,)))

    async def _safety(self, state: TriageState) -> TriageUpdate:
        case = await self._store.load(state["case_id"])
        if case.status.state is CaseState.CLOSED:
            # The message was saved before the close, so it reopens the case as a reply does (D20).
            reopen = case.change(case.status.reopen())
            await self._commit(state, AuditEntry(SAFETY, "reopened"), reopen)
            case = await self._store.load(state["case_id"])
        terms = self._policy.safety.hits(state["text"])
        if terms:
            task = TaskDraft(
                step_id=f"{state['batch_key']}/emergency",
                kind=TaskKind.EMERGENCY,
                category=None,
                urgency=Urgency.URGENT,
                state=TaskState.HELD,
                summary=state["text"],
            )
            await self._commit(
                state,
                AuditEntry(SAFETY, "emergency", {"input": state["text"], "terms": terms}),
                status=case.change(case.status.emergency(self._clock.now())),
                tasks=(task,),
            )
            return {"next": END}
        if case.status.state is CaseState.PARKED:
            await self._commit(state, AuditEntry(SAFETY, "stop_parked", {"input": state["text"]}))
            return {"next": END, "parked": True}
        if not triages_follow_up(case.status, await self._store.task_states(state["case_id"])):
            await self._commit(state, AuditEntry(SAFETY, "joined", {"input": state["text"]}))
            return {"next": END}
        await self._commit(state, AuditEntry(SAFETY, "clear", {"input": state["text"]}))
        return {"next": VERIFY}

    async def _verify(self, state: TriageState) -> TriageUpdate:
        if state["restored"]:
            # Staff restored the case from a spam park: their verdict stands, no LLM call (D33).
            case = await self._store.load(state["case_id"])
            audit = AuditEntry(VERIFY, "restored", {"input": state["text"]})
            await self._commit(state, audit, case.change(case.status.understood()))
            return {"next": SPLIT}
        try:
            verdict = await self._llm.verify(state["text"])
        except LlmError:
            return {"next": LLM_FAILED, "failed_step": VERIFY}
        change = None
        if verdict is Verdict.GENUINE:
            case = await self._store.load(state["case_id"])
            change = case.change(case.status.understood())
        await self._commit(state, AuditEntry(VERIFY, verdict, {"input": state["text"]}), change)
        return {"next": _AFTER_VERDICT[verdict]}

    async def _park(self, state: TriageState) -> TriageUpdate:
        case = await self._store.load(state["case_id"])
        # A ticket may have been saved since the entry check; a parked case has none (I8).
        if in_action(await self._store.task_states(state["case_id"])):
            await self._commit(
                state, AuditEntry(PARK, "refused_in_action"), case.change(case.status)
            )
            return {"next": END}
        status = case.status.park(StateReason.SPAM)
        await self._commit(state, AuditEntry(PARK, status.state), case.change(status))
        return {"next": END, "parked": status.state is CaseState.PARKED}

    async def _clarify(self, state: TriageState) -> TriageUpdate:
        case = await self._store.load(state["case_id"])
        status = case.status.clarify(self._policy.clarify_max_rounds, self._clock.now())
        decision = "asked" if status.state is CaseState.OPEN else status.state
        audit = AuditEntry(CLARIFY, decision, {"round": status.clarify_rounds})
        await self._commit(state, audit, case.change(status))
        return {"next": END}

    async def _split(self, state: TriageState) -> TriageUpdate:
        try:
            proposed = await self._llm.split(state["text"])
        except LlmError:
            return {"next": LLM_FAILED, "failed_step": SPLIT}
        intents = [intent.strip() for intent in proposed if intent.strip()] or [state["text"]]
        audit = AuditEntry(SPLIT, str(len(intents)), {"intents": intents})
        await self._commit(state, audit)
        return {"next": CLASSIFY, "intents": intents, "index": 0}

    async def _classify(self, state: TriageState) -> TriageUpdate:
        intent = state["intents"][state["index"]]
        try:
            proposal = await self._llm.classify(intent, state["pick"])
        except LlmError:
            return {"next": LLM_FAILED, "failed_step": CLASSIFY}
        detail: dict[str, AuditValue] = {
            "intent": intent,
            "category": proposal.category,
            "urgency": proposal.urgency,
        }
        if state["pick"] is not None:
            detail["pick"] = state["pick"]
        await self._commit(state, AuditEntry(CLASSIFY, proposal.route, detail))
        return {"next": ROUTE_GUARD, "classification": proposal}

    async def _route_guard(self, state: TriageState) -> TriageUpdate:
        proposal = state["classification"]
        if proposal is None:
            raise RuntimeError("route guard ran without a classification")
        case = await self._store.load(state["case_id"])
        decision = guard_route(
            proposal.category,
            proposal.route,
            case.scope,
            self._clock.today(),
            self._policy.held_categories,
        )
        step_id = _step_id(state)
        task = TaskDraft(
            step_id=step_id,
            kind=decision.kind,
            category=proposal.category,
            urgency=proposal.urgency,
            state=decision.state,
            summary=state["intents"][state["index"]],
            fault_type=(proposal.fault_type or FaultType.OTHER)
            if decision.kind is TaskKind.FAULT
            else None,
        )
        status = case.status.raise_urgency(proposal.urgency)
        if decision.state is TaskState.HELD:
            status = status.hold(StateReason.MONEY, self._clock.now())
        detail: dict[str, AuditValue] = {"step_id": step_id, "state": decision.state}
        audit = AuditEntry(ROUTE_GUARD, decision.kind, detail)
        await self._commit(state, audit, case.change(status), (task,))
        if decision.kind is TaskKind.QUESTION:
            return {"next": ANSWER}
        return await self._next_intent(state)

    async def _answer(self, state: TriageState) -> TriageUpdate:
        step_id = _step_id(state)
        try:
            checked = await self._answerer.answer(state["intents"][state["index"]])
        except LlmError:
            return {"next": LLM_FAILED, "failed_step": ANSWER}
        detail: dict[str, AuditValue] = {"step_id": step_id}
        if checked.proposed is not None:
            detail["proposed"] = checked.proposed
        answer = TaskAnswer(step_id, checked.text, checked.cited)
        await self._commit(state, AuditEntry(ANSWER, checked.outcome, detail), answers=(answer,))
        return await self._next_intent(state)

    async def _dispatch(self, state: TriageState) -> TriageUpdate:
        update = await self._next_task(state["case_id"])
        if update["next"] == END:
            # Every task routed and nothing left to act on: D20 closes the case if all are done.
            await self._store.close_if_done(state["case_id"], self._clock.now())
        return update

    async def _next_task(self, case_id: int) -> TriageUpdate:
        case = await self._store.load(case_id)
        if case.status.state is CaseState.PARKED:
            return {"next": END}
        # Faults go first: urgent work jumps the queue.
        update = await self._faults.next_step(case_id)
        if update is None:
            update = await self._tables.next_step(case_id)
        return update or {"next": END}

    async def _llm_failed(self, state: TriageState) -> TriageUpdate:
        case = await self._store.load(state["case_id"])
        status = case.status.hold(StateReason.LLM_FAILED, self._clock.now())
        audit = AuditEntry(LLM_FAILED, status.state, {"failed_step": state["failed_step"]})
        await self._commit(state, audit, case.change(status))
        return {"next": END}

    async def _commit(
        self,
        state: TriageState,
        audit: AuditEntry,
        status: StatusChange | None = None,
        tasks: tuple[TaskDraft, ...] = (),
        answers: tuple[TaskAnswer, ...] = (),
    ) -> None:
        await self._store.commit(state["case_id"], StepRecord(audit, status, tasks, answers))

    async def _next_intent(self, state: TriageState) -> TriageUpdate:
        index = state["index"] + 1
        if index < len(state["intents"]):
            return {"next": CLASSIFY, "index": index}
        return {"next": DISPATCH, "index": index}

    def _build(self) -> CompiledStateGraph[TriageState, Any, TriageState, TriageState]:
        builder = StateGraph(TriageState)
        nodes = {
            SAFETY: self._safety,
            VERIFY: self._verify,
            PARK: self._park,
            CLARIFY: self._clarify,
            SPLIT: self._split,
            CLASSIFY: self._classify,
            ROUTE_GUARD: self._route_guard,
            ANSWER: self._answer,
            LLM_FAILED: self._llm_failed,
            CONFIRM_SPLIT: self._faults.confirm_split,
            REPORT: self._faults.report,
            SAME: self._faults.same,
            SPECIALIST: self._faults.specialist,
            LINK: self._faults.link,
            BOOKING: self._tables.book,
            DISPATCH: self._dispatch,
        }
        for name, node in nodes.items():
            builder.add_node(name, node, retry_policy=_STALE_RETRY)
            builder.add_conditional_edges(name, _next_node, [*nodes, END])
        builder.add_conditional_edges(START, _next_node, list(nodes))
        return builder.compile()


def _next_node(state: TriageState) -> str:
    return state["next"]


def _step_id(state: TriageState) -> str:
    return f"{state['batch_key']}/t{state['index']}"

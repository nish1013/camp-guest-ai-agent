from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import RetryPolicy

from camp_agent.clock import Clock
from camp_agent.domain.audit_entry import AuditEntry, AuditValue
from camp_agent.domain.case_state import CaseState, StateReason
from camp_agent.domain.route_guard import TaskKind, TaskState, guard_route
from camp_agent.domain.urgency import Urgency
from camp_agent.graph.guide_answerer import GuideAnswerer
from camp_agent.graph.stale_case_error import StaleCaseError
from camp_agent.graph.triage_graph import PendingMessage
from camp_agent.graph.triage_store import TriageStore
from camp_agent.graph.triage_types import (
    StatusChange,
    StepRecord,
    TaskAnswer,
    TaskDraft,
    TriagePolicy,
)
from camp_agent.llm.llm_error import LlmError
from camp_agent.llm.llm_port import LlmPort
from camp_agent.llm.llm_types import Classification, Verdict


class TriageState(TypedDict):
    case_id: int
    batch_key: str
    text: str
    intents: list[str]
    index: int
    classification: Classification | None
    failed_step: str
    next: str


class TriageUpdate(TypedDict, total=False):
    intents: list[str]
    index: int
    classification: Classification
    failed_step: str
    next: str


SAFETY = "safety"
VERIFY = "verify"
PARK = "park"
CLARIFY = "clarify"
SPLIT = "split"
CLASSIFY = "classify"
ROUTE_GUARD = "route_guard"
ANSWER = "answer"
LLM_FAILED = "llm_failed"

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
    ) -> None:
        self._llm = llm
        self._store = store
        self._clock = clock
        self._policy = policy
        self._answerer = answerer
        self._graph = self._build()

    async def run(self, case_id: int, batch: list[PendingMessage]) -> None:
        start: TriageState = {
            "case_id": case_id,
            "batch_key": f"m{batch[0].id}",
            "text": "\n".join(message.text for message in batch),
            "intents": [],
            "index": 0,
            "classification": None,
            "failed_step": "",
            "next": "",
        }
        await self._graph.ainvoke(start, {"recursion_limit": _RECURSION_LIMIT})

    async def _safety(self, state: TriageState) -> TriageUpdate:
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
            return {"next": END}
        await self._commit(state, AuditEntry(SAFETY, "clear", {"input": state["text"]}))
        return {"next": VERIFY}

    async def _verify(self, state: TriageState) -> TriageUpdate:
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
        status = case.status.park(StateReason.SPAM)
        await self._commit(state, AuditEntry(PARK, status.state), case.change(status))
        return {"next": END}

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
            proposal = await self._llm.classify(intent)
        except LlmError:
            return {"next": LLM_FAILED, "failed_step": CLASSIFY}
        detail: dict[str, AuditValue] = {
            "intent": intent,
            "category": proposal.category,
            "urgency": proposal.urgency,
        }
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
            case.scope is not None,
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
        )
        status = case.status.raise_urgency(proposal.urgency)
        if decision.state is TaskState.HELD:
            status = status.hold(StateReason.MONEY, self._clock.now())
        detail: dict[str, AuditValue] = {"step_id": step_id, "state": decision.state}
        audit = AuditEntry(ROUTE_GUARD, decision.kind, detail)
        await self._commit(state, audit, case.change(status), (task,))
        if decision.kind is TaskKind.QUESTION:
            return {"next": ANSWER}
        return _next_intent(state)

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
        return _next_intent(state)

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
        }
        for name, node in nodes.items():
            builder.add_node(name, node, retry_policy=_STALE_RETRY)
            builder.add_conditional_edges(name, _next_node, [*nodes, END])
        builder.add_edge(START, SAFETY)
        return builder.compile()


def _next_node(state: TriageState) -> str:
    return state["next"]


def _step_id(state: TriageState) -> str:
    return f"{state['batch_key']}/t{state['index']}"


def _next_intent(state: TriageState) -> TriageUpdate:
    index = state["index"] + 1
    return {"next": CLASSIFY if index < len(state["intents"]) else END, "index": index}

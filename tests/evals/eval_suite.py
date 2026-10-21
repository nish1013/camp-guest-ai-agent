from collections.abc import Awaitable, Callable
from typing import Any

from pydantic_evals import Dataset
from pydantic_evals.reporting import EvaluationReport

from camp_agent.domain.cases import CaseState
from camp_agent.domain.citation_check import CheckedAnswer
from camp_agent.domain.routing import TaskKind
from camp_agent.graph.guide_answerer import GuideAnswerer
from camp_agent.graph.langgraph_triage import LangGraphTriage
from camp_agent.graph.triage import PendingMessage
from camp_agent.llm.port import (
    Classification,
    LlmPort,
    SameProblem,
    TableArgs,
    TableBrief,
    TicketArgs,
    TicketBrief,
    Verdict,
)
from tests.evals import eval_datasets
from tests.evals.eval_constants import C12, POLICY, TODAY
from tests.evals.eval_types import ClassifyInput, GraphOutcome, SameProblemInput, TicketInput
from tests.fakes import FakeTickets, InMemoryTriageStore, demo_guide, demo_section, oct_19

type AnyReport = EvaluationReport[Any, Any, Any]

_CASE = 1


def failing_cases(report: AnyReport) -> list[str]:
    errored = [failure.name for failure in report.failures]
    failed = [
        case.name
        for case in report.cases
        if case.evaluator_failures or not all(a.value for a in case.assertions.values())
    ]
    return errored + failed


class EvalSuite:
    def __init__(self, llm: LlmPort) -> None:
        self._llm = llm
        self._answerer = GuideAnswerer(llm, demo_guide(), demo_section("reception").body)

    async def run(self) -> list[AnyReport]:
        return [
            await self.verify(),
            await self.safety(),
            await self.split(),
            await self.classify(),
            await self.same_problem(),
            await self.tickets(),
            await self.tables(),
            await self.guide(),
        ]

    async def verify(self) -> EvaluationReport[str, Verdict, None]:
        return await _evaluate(eval_datasets.verify_dataset(), self._llm.verify)

    async def safety(self) -> EvaluationReport[str, GraphOutcome, None]:
        return await _evaluate(eval_datasets.safety_dataset(), self._triage)

    async def split(self) -> EvaluationReport[str, list[str], None]:
        return await _evaluate(eval_datasets.split_dataset(), self._llm.split)

    async def classify(self) -> EvaluationReport[ClassifyInput, Classification, None]:
        return await _evaluate(eval_datasets.classify_dataset(), self._classify)

    async def same_problem(self) -> EvaluationReport[SameProblemInput, SameProblem, None]:
        return await _evaluate(eval_datasets.same_problem_dataset(), self._same)

    async def tickets(self) -> EvaluationReport[TicketInput, TicketArgs, None]:
        return await _evaluate(eval_datasets.ticket_dataset(), self._ticket)

    async def tables(self) -> EvaluationReport[str, TableArgs, None]:
        return await _evaluate(eval_datasets.table_dataset(), self._table)

    async def guide(self) -> EvaluationReport[str, CheckedAnswer, None]:
        return await _evaluate(eval_datasets.guide_dataset(), self._answer)

    async def _triage(self, text: str) -> GraphOutcome:
        store = InMemoryTriageStore()
        store.add_case(_CASE, C12)
        graph = LangGraphTriage(self._llm, store, oct_19(), POLICY, self._answerer, FakeTickets())
        await graph.run(_CASE, [PendingMessage(1, text)])
        return GraphOutcome(
            emergency=any(task.kind is TaskKind.EMERGENCY for task in store.tasks),
            parked=store.status(_CASE).state is CaseState.PARKED,
        )

    async def _classify(self, inputs: ClassifyInput) -> Classification:
        return await self._llm.classify(inputs.intent, inputs.pick)

    async def _same(self, inputs: SameProblemInput) -> SameProblem:
        return await self._llm.same_problem(inputs.fault, inputs.earlier)

    async def _ticket(self, inputs: TicketInput) -> TicketArgs:
        return await self._llm.draft_ticket(inputs.team, TicketBrief(inputs.fault, C12.cabin))

    async def _table(self, request: str) -> TableArgs:
        brief = TableBrief(request, C12.cabin, TODAY, C12.stay_from, C12.stay_to)
        return await self._llm.draft_table(brief)

    async def _answer(self, question: str) -> CheckedAnswer:
        return await self._answerer.answer(question)


async def _evaluate[InputsT, OutputT](
    dataset: Dataset[InputsT, OutputT, None], task: Callable[[InputsT], Awaitable[OutputT]]
) -> EvaluationReport[InputsT, OutputT, None]:
    return await dataset.evaluate(task, name=dataset.name, progress=False)

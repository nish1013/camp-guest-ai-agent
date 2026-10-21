from collections.abc import Sequence

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings

from camp_agent.domain.faults import OpenReport
from camp_agent.domain.guest_status import QuickPick
from camp_agent.domain.routing import Team
from camp_agent.guide.port import GuideSection
from camp_agent.llm import prompts
from camp_agent.llm.port import (
    Classification,
    GuideAnswer,
    LlmError,
    SameProblem,
    SplitOutput,
    TableArgs,
    TableBrief,
    TicketArgs,
    TicketBrief,
    Verdict,
    VerifyOutput,
)


class PydanticAiLlm:
    def __init__(self, model: Model | str, timeout_s: float) -> None:
        settings = ModelSettings(timeout=timeout_s)
        self._verify = self._agent(model, VerifyOutput, prompts.VERIFY, settings)
        self._split = self._agent(model, SplitOutput, prompts.SPLIT, settings)
        self._classify = self._agent(model, Classification, prompts.CLASSIFY, settings)
        self._answer = self._agent(model, GuideAnswer, prompts.ANSWER, settings)
        self._same = self._agent(model, SameProblem, prompts.SAME_PROBLEM, settings)
        self._specialists = {
            team: self._agent(model, TicketArgs, instructions, settings)
            for team, instructions in prompts.SPECIALISTS.items()
        }
        self._restaurant = self._agent(model, TableArgs, prompts.RESTAURANT, settings)

    async def verify(self, text: str) -> Verdict:
        return (await self._run(self._verify, text)).verdict

    async def split(self, text: str) -> list[str]:
        return (await self._run(self._split, text)).intents

    async def classify(self, intent: str, hint: QuickPick | None = None) -> Classification:
        return await self._run(self._classify, prompts.classify_input(intent, hint))

    async def answer(self, question: str, sections: Sequence[GuideSection]) -> GuideAnswer:
        return await self._run(self._answer, prompts.answer_input(question, sections))

    async def same_problem(self, fault: str, earlier: Sequence[OpenReport]) -> SameProblem:
        return await self._run(self._same, prompts.same_problem_input(fault, earlier))

    async def draft_ticket(self, team: Team, brief: TicketBrief) -> TicketArgs:
        return await self._run(self._specialists[team], prompts.ticket_input(brief))

    async def draft_table(self, brief: TableBrief) -> TableArgs:
        return await self._run(self._restaurant, prompts.table_input(brief))

    async def _run[T: BaseModel](self, agent: Agent[None, T], prompt: str) -> T:
        try:
            result = await agent.run(prompt)
        # Any failure of the provider, the network or the output schema is the same outcome for
        # the case: bounded retries, then held for a human (D16).
        except Exception as error:
            raise LlmError(type(error).__name__) from error
        return result.output

    def _agent[T: BaseModel](
        self, model: Model | str, output: type[T], instructions: str, settings: ModelSettings
    ) -> Agent[None, T]:
        return Agent(
            model,
            output_type=output,
            instructions=instructions,
            model_settings=settings,
            defer_model_check=True,
        )

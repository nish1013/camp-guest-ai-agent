from collections.abc import Sequence
from typing import Protocol

from camp_agent.domain.cabin_reports import OpenReport
from camp_agent.domain.specialist import Team
from camp_agent.guide.guide_types import GuideSection
from camp_agent.llm.llm_types import (
    Classification,
    GuideAnswer,
    SameProblem,
    TableArgs,
    TableBrief,
    TicketArgs,
    TicketBrief,
    Verdict,
)


class LlmPort(Protocol):
    async def verify(self, text: str) -> Verdict: ...

    async def split(self, text: str) -> list[str]: ...

    async def classify(self, intent: str) -> Classification: ...

    async def answer(self, question: str, sections: Sequence[GuideSection]) -> GuideAnswer: ...

    async def same_problem(self, fault: str, earlier: Sequence[OpenReport]) -> SameProblem: ...

    async def draft_ticket(self, team: Team, brief: TicketBrief) -> TicketArgs: ...

    async def draft_table(self, brief: TableBrief) -> TableArgs: ...

from collections.abc import Awaitable, Callable, Sequence

import anyio

from camp_agent.domain.faults import OpenReport
from camp_agent.domain.guest_status import QuickPick
from camp_agent.domain.routing import Team
from camp_agent.guide.port import GuideSection
from camp_agent.llm.port import (
    Classification,
    GuideAnswer,
    LlmError,
    LlmPort,
    SameProblem,
    TableArgs,
    TableBrief,
    TicketArgs,
    TicketBrief,
    Verdict,
)


class RetryingLlm:
    def __init__(self, inner: LlmPort, attempts: int, delay_s: float) -> None:
        if attempts < 1:
            raise ValueError("attempts must be at least 1")
        self._inner = inner
        self._attempts = attempts
        self._delay_s = delay_s

    async def verify(self, text: str) -> Verdict:
        return await self._attempt(lambda: self._inner.verify(text))

    async def split(self, text: str) -> list[str]:
        return await self._attempt(lambda: self._inner.split(text))

    async def classify(self, intent: str, hint: QuickPick | None = None) -> Classification:
        return await self._attempt(lambda: self._inner.classify(intent, hint))

    async def answer(self, question: str, sections: Sequence[GuideSection]) -> GuideAnswer:
        return await self._attempt(lambda: self._inner.answer(question, sections))

    async def same_problem(self, fault: str, earlier: Sequence[OpenReport]) -> SameProblem:
        return await self._attempt(lambda: self._inner.same_problem(fault, earlier))

    async def draft_ticket(self, team: Team, brief: TicketBrief) -> TicketArgs:
        return await self._attempt(lambda: self._inner.draft_ticket(team, brief))

    async def draft_table(self, brief: TableBrief) -> TableArgs:
        return await self._attempt(lambda: self._inner.draft_table(brief))

    async def _attempt[T](self, call: Callable[[], Awaitable[T]]) -> T:
        for attempt in range(1, self._attempts + 1):
            try:
                return await call()
            except LlmError:
                if attempt == self._attempts:
                    raise
                await anyio.sleep(self._delay_s)
        raise AssertionError("unreachable")

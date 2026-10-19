from collections.abc import Sequence
from typing import Protocol

from camp_agent.guide.guide_types import GuideSection
from camp_agent.llm.llm_types import Classification, GuideAnswer, Verdict


class LlmPort(Protocol):
    async def verify(self, text: str) -> Verdict: ...

    async def split(self, text: str) -> list[str]: ...

    async def classify(self, intent: str) -> Classification: ...

    async def answer(self, question: str, sections: Sequence[GuideSection]) -> GuideAnswer: ...

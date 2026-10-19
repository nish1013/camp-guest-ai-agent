from typing import Protocol

from camp_agent.llm.llm_types import Classification, Verdict


class LlmPort(Protocol):
    async def verify(self, text: str) -> Verdict: ...

    async def split(self, text: str) -> list[str]: ...

    async def classify(self, intent: str) -> Classification: ...

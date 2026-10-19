from collections.abc import Awaitable, Callable, Sequence

import anyio

from camp_agent.guide.guide_types import GuideSection
from camp_agent.llm.llm_error import LlmError
from camp_agent.llm.llm_port import LlmPort
from camp_agent.llm.llm_types import Classification, GuideAnswer, Verdict


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

    async def classify(self, intent: str) -> Classification:
        return await self._attempt(lambda: self._inner.classify(intent))

    async def answer(self, question: str, sections: Sequence[GuideSection]) -> GuideAnswer:
        return await self._attempt(lambda: self._inner.answer(question, sections))

    async def _attempt[T](self, call: Callable[[], Awaitable[T]]) -> T:
        for attempt in range(1, self._attempts + 1):
            try:
                return await call()
            except LlmError:
                if attempt == self._attempts:
                    raise
                await anyio.sleep(self._delay_s)
        raise AssertionError("unreachable")

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from camp_agent.domain.route_guard import Category, Route
from camp_agent.domain.urgency import Urgency
from camp_agent.guide.guide_types import GuideSection
from camp_agent.llm.llm_error import LlmError
from camp_agent.llm.llm_prompts import answer_input
from camp_agent.llm.llm_types import Classification, GuideAnswer, Verdict
from camp_agent.llm.pydantic_ai_llm import PydanticAiLlm
from camp_agent.llm.retrying_llm import RetryingLlm
from tests.fakes import FakeLlm

pytestmark = pytest.mark.anyio

POOL = GuideSection("pool-hours", "Pool hours", "Open 08:00-20:00.")


class FlakyLlm(FakeLlm):
    def __init__(self, failures: int) -> None:
        super().__init__()
        self._failures = failures

    async def verify(self, text: str) -> Verdict:
        self.calls.append("verify")
        if len(self.calls) <= self._failures:
            raise LlmError("timeout")
        return Verdict.GENUINE


def broken(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    raise ConnectionError("provider down")


async def test_d48_output_parsed() -> None:
    model = TestModel(
        custom_output_args={"category": "refund", "route": "money", "urgency": "normal"}
    )

    classification = await PydanticAiLlm(model, timeout_s=1).classify("refund please")

    assert classification == Classification(
        category=Category.REFUND, route=Route.MONEY, urgency=Urgency.NORMAL
    )


async def test_d17_answer_parsed() -> None:
    model = TestModel(custom_output_args={"text": "08:00-20:00", "section_id": "pool-hours"})

    answer = await PydanticAiLlm(model, timeout_s=1).answer("pool?", [POOL])

    assert answer == GuideAnswer(text="08:00-20:00", section_id="pool-hours")


def test_d17_answer_input_names_ids() -> None:
    text = answer_input("When does the pool open?", [POOL])

    assert "[pool-hours] Pool hours\nOpen 08:00-20:00." in text
    assert text.endswith("Guest question: When does the pool open?")


async def test_d16_provider_error_is_llm_error() -> None:
    with pytest.raises(LlmError, match="ConnectionError"):
        await PydanticAiLlm(FunctionModel(broken), timeout_s=1).verify("hello")


async def test_d16_retry_then_succeed() -> None:
    inner = FlakyLlm(failures=2)

    assert await RetryingLlm(inner, attempts=3, delay_s=0).verify("hello") is Verdict.GENUINE
    assert len(inner.calls) == 3


async def test_d16_retries_are_bounded() -> None:
    inner = FlakyLlm(failures=3)

    with pytest.raises(LlmError):
        await RetryingLlm(inner, attempts=3, delay_s=0).verify("hello")
    assert len(inner.calls) == 3

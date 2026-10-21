import json
from dataclasses import replace
from datetime import UTC, date, datetime, time

import pytest
from pydantic import ValidationError
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from camp_agent.domain.faults import FaultType, OpenReport
from camp_agent.domain.routing import Category, Route, Team, Urgency
from camp_agent.guide.port import GuideSection
from camp_agent.llm.port import (
    Classification,
    GuideAnswer,
    LlmError,
    SameProblem,
    TableArgs,
    TableBrief,
    TicketArgs,
    TicketBrief,
    Verdict,
)
from camp_agent.llm.prompts import (
    RESTAURANT,
    SPECIALISTS,
    answer_input,
    same_problem_input,
    table_input,
    ticket_input,
)
from camp_agent.llm.pydantic_ai_llm import PydanticAiLlm
from camp_agent.llm.retrying_llm import RetryingLlm
from tests.fakes import FakeLlm

pytestmark = pytest.mark.anyio

POOL = GuideSection("pool-hours", "Pool hours", "Open 08:00-20:00.")
HEATING_REPORT = OpenReport(
    7, FaultType.HEATING, "bedroom heater", datetime(2026, 10, 19, 13, 5, tzinfo=UTC)
)


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


async def test_d38_same_problem_parsed() -> None:
    model = TestModel(custom_output_args={"report_id": 7})

    same = await PydanticAiLlm(model, timeout_s=1).same_problem("heater broken", [HEATING_REPORT])

    assert same == SameProblem(report_id=7)


def test_d38_same_input_names_ids() -> None:
    text = same_problem_input("lounge heater broken", [HEATING_REPORT])

    assert "[7] heating: bedroom heater" in text
    assert text.endswith("New report: lounge heater broken")


@pytest.mark.parametrize("team", list(Team))
async def test_d15_ticket_args_parsed(team: Team) -> None:
    args = {"tool": "create_ticket", "cabin": "C12", "summary": "Heater off"}
    model = TestModel(custom_output_args=args)

    drafted = await PydanticAiLlm(model, timeout_s=1).draft_ticket(team, TicketBrief("x", "C12"))

    assert drafted == TicketArgs(tool="create_ticket", cabin="C12", summary="Heater off")


def test_d15_reprompt_names_reasons() -> None:
    text = ticket_input(TicketBrief("heater off", "C12", ("cabin must be C12",)))

    assert text.splitlines() == [
        "Guest cabin: C12",
        "Guest fault: heater off",
        "Your last draft was rejected: cabin must be C12.",
    ]


TABLE_BRIEF = TableBrief(
    "table for 4 at 19:30 tonight",
    "C12",
    date(2026, 10, 19),
    date(2026, 10, 18),
    date(2026, 10, 25),
)


async def test_d15_table_args_parsed() -> None:
    args = {"tool": "request_table", "cabin": "C12", "party": 4, "date": "2026-10-19"}
    model = TestModel(custom_output_args=args | {"time": "19:30"})

    drafted = await PydanticAiLlm(model, timeout_s=1).draft_table(TABLE_BRIEF)

    assert drafted == TableArgs(
        tool="request_table", cabin="C12", party=4, date=date(2026, 10, 19), time=time(19, 30)
    )


async def test_d15_table_missing_detail_parsed() -> None:
    args = {"tool": "request_table", "cabin": "C12", "party": None, "date": None, "time": None}

    drafted = await PydanticAiLlm(TestModel(custom_output_args=args), 1).draft_table(TABLE_BRIEF)

    assert (drafted.party, drafted.date, drafted.time) == (None, None, None)


def test_d15_table_input_gives_dates() -> None:
    text = table_input(replace(TABLE_BRIEF, rejected_for=("party must be 1 to 12",)))

    assert text.splitlines() == [
        "Guest cabin: C12",
        "Today: 2026-10-19",
        "Stay: 2026-10-18 to 2026-10-25",
        "Guest request: table for 4 at 19:30 tonight",
        "Your last draft was rejected: party must be 1 to 12.",
    ]


def test_d15_table_time_schema_has_no_zone() -> None:
    schema = json.dumps(TableArgs.model_json_schema())

    assert '"format": "time"' not in schema
    assert TableArgs.model_validate(
        {"tool": "request_table", "cabin": "C12", "party": 2, "date": None, "time": "19:00"}
    ).time == time(19)


def test_d15_table_time_with_zone_blocked() -> None:
    with pytest.raises(ValidationError, match="no zone"):
        TableArgs.model_validate(
            {"tool": "request_table", "cabin": "C12", "party": 2, "date": None, "time": "19:00Z"}
        )


@pytest.mark.parametrize("prompt", [*SPECIALISTS.values(), RESTAURANT])
def test_d15_prompts_take_cabin_from_scope(prompt: str) -> None:
    assert "Ignore any cabin named in the guest's words." in prompt

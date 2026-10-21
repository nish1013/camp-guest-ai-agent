from datetime import date, time

import pytest

from camp_agent.llm.port import TableArgs, TicketArgs, Verdict
from tests.evals.eval_datasets import CROSS_CABIN_FAULT, CROSS_CABIN_TABLE, SAFETY_SPAM, SPAM
from tests.evals.eval_suite import EvalSuite, failing_cases
from tests.fakes import FakeLlm

pytestmark = pytest.mark.anyio


def table(cabin: str) -> TableArgs:
    return TableArgs(
        tool="request_table", cabin=cabin, party=2, date=date(2026, 10, 19), time=time(19, 30)
    )


async def test_us4_planted_cabin_fails() -> None:
    planted = TicketArgs(tool="create_ticket", cabin="C14", summary="Shower leaking")
    llm = FakeLlm(drafts={CROSS_CABIN_FAULT: [planted]})

    report = await EvalSuite(llm).tickets()

    assert failing_cases(report) == ["cross_cabin"]
    reasons = [r.reason for case in report.cases for r in case.assertions.values() if r.reason]
    assert reasons == ["cabin must be C12"]


async def test_us4_scope_cabin_passes() -> None:
    report = await EvalSuite(FakeLlm()).tickets()

    assert failing_cases(report) == []


async def test_us5_planted_cabin_fails() -> None:
    llm = FakeLlm(tables={CROSS_CABIN_TABLE: [table("C14")]})

    report = await EvalSuite(llm).tables()

    assert "cross_cabin" in failing_cases(report)


async def test_us5_scope_cabin_passes() -> None:
    llm = FakeLlm(tables={CROSS_CABIN_TABLE: [table("C12")]})

    report = await EvalSuite(llm).tables()

    assert "cross_cabin" not in failing_cases(report)


async def test_d49_llm_error_fails_case() -> None:
    report = await EvalSuite(FakeLlm(down=True)).tickets()

    assert failing_cases(report) == ["maintenance", "housekeeping", "cross_cabin"]


async def test_i9_safety_beats_spam() -> None:
    llm = FakeLlm(verdicts={text: Verdict.SPAM for text in (SPAM, SAFETY_SPAM)})

    report = await EvalSuite(llm).safety()

    assert failing_cases(report) == []

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from camp_agent.config import Settings
from camp_agent.domain.audit_entry import AuditEntry
from camp_agent.domain.case_status import CaseStatus
from camp_agent.domain.route_guard import Category, Route
from camp_agent.domain.scope import Scope
from camp_agent.domain.urgency import Urgency
from camp_agent.graph.stale_case_error import StaleCaseError
from camp_agent.graph.triage_types import (
    CaseSnapshot,
    StatusChange,
    StepRecord,
    TaskAnswer,
    TaskDraft,
)
from camp_agent.guide.guide_error import GuideError
from camp_agent.guide.guide_port import GuidePort
from camp_agent.guide.guide_types import GuideSection
from camp_agent.guide.markdown_guide import MarkdownGuide, parse_guide
from camp_agent.llm.llm_error import LlmError
from camp_agent.llm.llm_types import Classification, GuideAnswer, Verdict

CAMP_TZ = ZoneInfo("Europe/London")
QUESTION = Classification(
    category=Category.INFORMATION, route=Route.QUESTION, urgency=Urgency.NORMAL
)
NO_ANSWER = GuideAnswer(text="", section_id=None)


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def today(self) -> date:
        return self._now.astimezone(CAMP_TZ).date()

    def advance(self, delta: timedelta) -> None:
        self._now += delta


def oct_19(hour: int = 14) -> FakeClock:
    return FakeClock(datetime(2026, 10, 19, hour, tzinfo=CAMP_TZ).astimezone(UTC))


class SwitchableGuide:
    def __init__(self, inner: GuidePort) -> None:
        self._inner = inner
        self.down = False

    async def search(self, question: str) -> list[GuideSection]:
        self._check()
        return await self._inner.search(question)

    async def section(self, section_id: str) -> GuideSection | None:
        self._check()
        return await self._inner.section(section_id)

    def _check(self) -> None:
        if self.down:
            raise GuideError("down")


def demo_guide() -> SwitchableGuide:
    return SwitchableGuide(MarkdownGuide(Settings().guide_path))


def demo_section(section_id: str) -> GuideSection:
    return parse_guide(Settings().guide_path.read_text(encoding="utf-8"))[section_id]


class FakeLlm:
    def __init__(
        self,
        verdicts: dict[str, Verdict] | None = None,
        splits: dict[str, list[str]] | None = None,
        classes: dict[str, Classification] | None = None,
        answers: dict[str, GuideAnswer] | None = None,
        down: bool = False,
    ) -> None:
        self._verdicts = verdicts or {}
        self._splits = splits or {}
        self._classes = classes or {}
        self._answers = answers or {}
        self._down = down
        self.calls: list[str] = []
        self.offered: list[str] = []

    async def verify(self, text: str) -> Verdict:
        self._call("verify")
        return self._verdicts.get(text, Verdict.GENUINE)

    async def split(self, text: str) -> list[str]:
        self._call("split")
        return self._splits.get(text, [text])

    async def classify(self, intent: str) -> Classification:
        self._call("classify")
        return self._classes.get(intent, QUESTION)

    async def answer(self, question: str, sections: Sequence[GuideSection]) -> GuideAnswer:
        self._call("answer")
        self.offered = [section.id for section in sections]
        return self._answers.get(question, NO_ANSWER)

    def _call(self, name: str) -> None:
        self.calls.append(name)
        if self._down:
            raise LlmError("down")


class InMemoryTriageStore:
    def __init__(self) -> None:
        self.cases: dict[int, CaseSnapshot] = {}
        self.tasks: list[TaskDraft] = []
        self.answers: list[TaskAnswer] = []
        self.audit: list[AuditEntry] = []

    def add_case(self, case_id: int, scope: Scope | None = None) -> None:
        self.cases[case_id] = CaseSnapshot(CaseStatus(), scope, 0)

    async def load(self, case_id: int) -> CaseSnapshot:
        return self.cases[case_id]

    async def commit(self, case_id: int, step: StepRecord) -> None:
        if step.status is not None:
            self.write_status(case_id, step.status)
        self.tasks.extend(step.tasks)
        self.answers.extend(step.answers)
        self.audit.append(step.audit)

    def write_status(self, case_id: int, change: StatusChange) -> None:
        case = self.cases[case_id]
        if change.version != case.version:
            raise StaleCaseError(case_id)
        self.cases[case_id] = replace(case, status=change.status, version=case.version + 1)

    def status(self, case_id: int) -> CaseStatus:
        return self.cases[case_id].status

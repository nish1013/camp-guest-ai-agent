from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from camp_agent.domain.audit_entry import AuditEntry
from camp_agent.domain.case_status import CaseStatus
from camp_agent.domain.route_guard import Category, Route
from camp_agent.domain.scope import Scope
from camp_agent.domain.urgency import Urgency
from camp_agent.graph.triage_types import CaseSnapshot, StepRecord, TaskDraft
from camp_agent.llm.llm_error import LlmError
from camp_agent.llm.llm_types import Classification, Verdict

CAMP_TZ = ZoneInfo("Europe/London")
QUESTION = Classification(
    category=Category.INFORMATION, route=Route.QUESTION, urgency=Urgency.NORMAL
)


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


class FakeLlm:
    def __init__(
        self,
        verdicts: dict[str, Verdict] | None = None,
        splits: dict[str, list[str]] | None = None,
        classes: dict[str, Classification] | None = None,
        down: bool = False,
    ) -> None:
        self._verdicts = verdicts or {}
        self._splits = splits or {}
        self._classes = classes or {}
        self._down = down
        self.calls: list[str] = []

    async def verify(self, text: str) -> Verdict:
        self._call("verify")
        return self._verdicts.get(text, Verdict.GENUINE)

    async def split(self, text: str) -> list[str]:
        self._call("split")
        return self._splits.get(text, [text])

    async def classify(self, intent: str) -> Classification:
        self._call("classify")
        return self._classes.get(intent, QUESTION)

    def _call(self, name: str) -> None:
        self.calls.append(name)
        if self._down:
            raise LlmError("down")


class InMemoryTriageStore:
    def __init__(self) -> None:
        self.cases: dict[int, CaseSnapshot] = {}
        self.tasks: list[TaskDraft] = []
        self.audit: list[AuditEntry] = []

    def add_case(self, case_id: int, scope: Scope | None = None) -> None:
        self.cases[case_id] = CaseSnapshot(CaseStatus(), scope)

    async def load(self, case_id: int) -> CaseSnapshot:
        return self.cases[case_id]

    async def commit(self, case_id: int, step: StepRecord) -> None:
        if step.status is not None:
            self.cases[case_id] = replace(self.cases[case_id], status=step.status)
        self.tasks.extend(step.tasks)
        self.audit.append(step.audit)

    def status(self, case_id: int) -> CaseStatus:
        return self.cases[case_id].status

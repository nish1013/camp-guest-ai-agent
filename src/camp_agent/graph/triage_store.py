from typing import Protocol

from camp_agent.domain.cabin_reports import ReportDraft, SavedReport
from camp_agent.domain.fault_flow import FaultTask
from camp_agent.graph.triage_types import CaseSnapshot, LinkTarget, StepRecord, WaitingTask


class TriageStore(Protocol):
    async def load(self, case_id: int) -> CaseSnapshot: ...

    async def awaiting_scope(self, case_id: int) -> list[WaitingTask]: ...

    async def faults(self, case_id: int) -> list[FaultTask]: ...

    # One step of the CabinReports aggregate: the report records every open report in its cabin
    # that it was checked against (I4). A repeat step id returns the report already saved.
    async def save_report(self, case_id: int, draft: ReportDraft) -> SavedReport: ...

    async def link_target(self, report_id: int) -> LinkTarget | None: ...

    # One graph step: the case changes, its tasks and its audit entry in one transaction (I13).
    # Raises StaleCaseError when the case changed since the status was computed.
    async def commit(self, case_id: int, step: StepRecord) -> None: ...

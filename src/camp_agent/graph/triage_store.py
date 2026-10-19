from contextlib import AbstractAsyncContextManager
from typing import Protocol

from camp_agent.domain.cabin_reports import ReportDraft, SavedReport
from camp_agent.domain.fault_flow import FaultTask
from camp_agent.domain.route_guard import TaskState
from camp_agent.domain.table_flow import TableTask
from camp_agent.graph.triage_types import CaseSnapshot, LinkTarget, StepRecord, WaitingTask


class LockedCase(Protocol):
    case: CaseSnapshot

    async def commit(self, step: StepRecord) -> None: ...


class TriageStore(Protocol):
    async def load(self, case_id: int) -> CaseSnapshot: ...

    async def awaiting_scope(self, case_id: int) -> list[WaitingTask]: ...

    async def faults(self, case_id: int) -> list[FaultTask]: ...

    async def tables(self, case_id: int) -> list[TableTask]: ...

    async def task_states(self, case_id: int) -> list[TaskState]: ...

    # One step of the CabinReports aggregate: the report records every open report in its cabin
    # that it was checked against (I4). A repeat step id returns the report already saved.
    async def save_report(self, case_id: int, draft: ReportDraft) -> SavedReport: ...

    async def link_target(self, report_id: int) -> LinkTarget | None: ...

    # Holds the case row from the read to the commit, so no status write lands in between.
    def lock_case(self, case_id: int) -> AbstractAsyncContextManager[LockedCase]: ...

    # One graph step: the case changes, its tasks and its audit entry in one transaction (I13).
    # Raises StaleCaseError when the case changed since the status was computed.
    async def commit(self, case_id: int, step: StepRecord) -> None: ...

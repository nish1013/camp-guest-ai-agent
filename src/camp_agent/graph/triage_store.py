from typing import Protocol

from camp_agent.graph.triage_types import CaseSnapshot, StepRecord


class TriageStore(Protocol):
    async def load(self, case_id: int) -> CaseSnapshot: ...

    # One graph step: the case changes, its tasks and its audit entry in one transaction (I13).
    # Raises StaleCaseError when the case changed since the status was computed.
    async def commit(self, case_id: int, step: StepRecord) -> None: ...

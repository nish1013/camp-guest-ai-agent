from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PendingMessage:
    id: int
    text: str


class TriageGraph(Protocol):
    async def run(self, case_id: int, batch: list[PendingMessage]) -> None: ...

    # Tasks that waited for scope go on once the case has it (D2).
    async def resume(self, case_id: int) -> None: ...

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PendingMessage:
    id: int
    text: str


class TriageGraph(Protocol):
    async def run(self, case_id: int, batch: list[PendingMessage]) -> None: ...

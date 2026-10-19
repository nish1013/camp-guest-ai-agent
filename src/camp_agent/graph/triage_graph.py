from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


@dataclass(frozen=True)
class PendingMessage:
    id: int
    text: str
    # Queued again by a staff restore of a spam park: the spam verdict is overridden (D33).
    restored: bool = False


class BatchOutcome(StrEnum):
    TRIAGED = "triaged"
    # The batch stopped on a parked case; a staff restore queues it again.
    PARKED = "parked"


class TriageGraph(Protocol):
    async def run(self, case_id: int, batch: list[PendingMessage]) -> BatchOutcome: ...

    # Tasks that waited for scope go on once the case has it (D2).
    async def resume(self, case_id: int) -> None: ...


def next_batch(pending: list[PendingMessage]) -> list[PendingMessage]:
    # Restored messages run on their own, so the spam override never covers a new message.
    restored = pending[0].restored
    batch: list[PendingMessage] = []
    for message in pending:
        if message.restored is not restored:
            break
        batch.append(message)
    return batch

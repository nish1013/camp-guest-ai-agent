from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class StatusNotice:
    case_id: int
    status: str


class NotificationPort(Protocol):
    # Told when a case's guest status changes. It stores nothing the page reads (D22, D25).
    async def notify(self, notice: StatusNotice) -> None: ...


class CaseWatch(Protocol):
    # Called after a commit that may have changed what the guest sees. Never raises.
    async def changed(self, case_id: int) -> None: ...

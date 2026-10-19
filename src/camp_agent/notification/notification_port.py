from typing import Protocol

from camp_agent.notification.notification_types import StatusNotice


class NotificationPort(Protocol):
    # Told when a case's guest status changes. It stores nothing the page reads (D22, D25).
    async def notify(self, notice: StatusNotice) -> None: ...

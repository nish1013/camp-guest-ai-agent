import json
import logging

from camp_agent.notification.port import StatusNotice

log = logging.getLogger(__name__)


class LogNotifications:
    async def notify(self, notice: StatusNotice) -> None:
        log.info(
            json.dumps(
                {"event": "guest_status", "case_id": notice.case_id, "status": notice.status}
            )
        )

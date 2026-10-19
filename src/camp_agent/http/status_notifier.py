import hashlib
import logging

from markupsafe import Markup
from sqlalchemy.ext.asyncio import AsyncEngine

from camp_agent.db.case_repository import CaseRepository
from camp_agent.db.status_notice_repository import StatusNoticeRepository
from camp_agent.http.case_panels import STATUS, CasePanels
from camp_agent.notification.notification_port import NotificationPort
from camp_agent.notification.notification_types import StatusNotice

log = logging.getLogger(__name__)


class StatusNotifier:
    # Renders the status lines the page shows and tells the port only when they differ from the
    # last ones sent. Runs after the commit; any failure is logged and the case is untouched.
    def __init__(self, engine: AsyncEngine, panels: CasePanels, port: NotificationPort) -> None:
        self._engine = engine
        self._panels = panels
        self._port = port

    async def changed(self, case_id: int) -> None:
        try:
            await self._notify_if_changed(case_id)
        except Exception:
            log.exception("status notice failed for case %s", case_id)

    async def _notify_if_changed(self, case_id: int) -> None:
        async with self._engine.connect() as conn:
            case = await CaseRepository(conn).find(case_id)
        if case is None:
            return
        lines = (await self._panels.parts(case))[STATUS]
        digest = hashlib.sha256(lines.encode()).hexdigest()
        async with self._engine.begin() as conn:
            if not await StatusNoticeRepository(conn).claim(case_id, digest):
                return
        status = " ".join(Markup(lines).striptags().split())
        await self._port.notify(StatusNotice(case_id, status))

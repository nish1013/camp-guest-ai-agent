import logging

import anyio

from camp_agent.intake.apply_ticket_status import ApplyTicketStatus

log = logging.getLogger(__name__)


class OutboxPoller:
    def __init__(self, handler: ApplyTicketStatus, interval_s: float) -> None:
        self._handler = handler
        self._interval_s = interval_s

    async def run(self) -> None:
        while True:
            try:
                await self._handler.handle_pending()
            except Exception:
                # The outbox keeps every unhandled event, so the next pass retries it.
                log.exception("ticket status pass failed")
            await anyio.sleep(self._interval_s)

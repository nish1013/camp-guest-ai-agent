import json
import logging

import pytest

from camp_agent.notification.log_notifications import LogNotifications
from camp_agent.notification.notification_types import StatusNotice

pytestmark = pytest.mark.anyio


async def test_d22_one_structured_line(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="camp_agent.notification.log_notifications"):
        await LogNotifications().notify(StatusNotice(7, "Status: Received"))

    assert [json.loads(record.message) for record in caplog.records] == [
        {"event": "guest_status", "case_id": 7, "status": "Status: Received"}
    ]

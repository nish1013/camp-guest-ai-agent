from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

CAMP_TZ = ZoneInfo("Europe/London")


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def today(self) -> date:
        return self._now.astimezone(CAMP_TZ).date()

    def advance(self, delta: timedelta) -> None:
        self._now += delta


def oct_19(hour: int = 14) -> FakeClock:
    return FakeClock(datetime(2026, 10, 19, hour, tzinfo=CAMP_TZ).astimezone(UTC))

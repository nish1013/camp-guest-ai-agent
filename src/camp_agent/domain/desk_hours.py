from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class DeskHours:
    opens: time
    closes: time
    tz: ZoneInfo

    def __post_init__(self) -> None:
        if self.opens >= self.closes:
            raise ValueError("the desk must open before it closes")

    def is_open(self, at: datetime) -> bool:
        local = at.astimezone(self.tz).time()
        return self.opens <= local < self.closes

    def staffed_between(self, start: datetime, end: datetime) -> timedelta:
        staffed = timedelta()
        day = start.astimezone(self.tz).date()
        last = end.astimezone(self.tz).date()
        while day <= last:
            opens = datetime.combine(day, self.opens, self.tz)
            closes = datetime.combine(day, self.closes, self.tz)
            overlap = min(end, closes) - max(start, opens)
            staffed += max(overlap, timedelta())
            day += timedelta(days=1)
        return staffed


def is_overdue(held_at: datetime | None, now: datetime, desk: DeskHours, gate: timedelta) -> bool:
    # Only staffed time counts: a case held at night starts its clock at opening (D30).
    return held_at is not None and desk.staffed_between(held_at, now) >= gate

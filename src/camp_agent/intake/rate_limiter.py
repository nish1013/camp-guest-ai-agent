from collections import deque
from datetime import datetime, timedelta


class SlidingWindowLimiter:
    def __init__(self, max_events: int, window: timedelta) -> None:
        self._max = max_events
        self._window = window
        self._events: dict[str, deque[datetime]] = {}
        self._last_sweep: datetime | None = None

    def allow(self, keys: list[str], now: datetime) -> bool:
        cutoff = now - self._window
        self._sweep_if_due(now, cutoff)
        for key in keys:
            self._prune(key, cutoff)
        if any(len(self._events.get(key, ())) >= self._max for key in keys):
            return False
        for key in keys:
            self._events.setdefault(key, deque()).append(now)
        return True

    def _prune(self, key: str, cutoff: datetime) -> None:
        events = self._events.get(key)
        if events is None:
            return
        while events and events[0] <= cutoff:
            events.popleft()
        if not events:
            del self._events[key]

    def _sweep_if_due(self, now: datetime, cutoff: datetime) -> None:
        if self._last_sweep is not None and now - self._last_sweep < self._window:
            return
        self._last_sweep = now
        for key in list(self._events):
            self._prune(key, cutoff)

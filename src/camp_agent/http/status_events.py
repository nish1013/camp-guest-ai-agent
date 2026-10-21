import hashlib
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping

import anyio

type RenderParts = Callable[[], Awaitable[Mapping[str, str] | None]]


RETRY_MS = 3000


def event_id(parts: Mapping[str, str]) -> str:
    return ",".join(f"{name}:{_digest(html)}" for name, html in parts.items())


class StatusEvents:
    # Each part is sent when its HTML changes, so a form the guest is typing into is not swapped
    # out by a status line. The event id names what the page holds; a reconnect sends it back.
    def __init__(self, render: RenderParts, poll_s: float, lifetime_s: float) -> None:
        self._render = render
        self._poll_s = poll_s
        self._lifetime_s = lifetime_s

    async def stream(self, seen: str | None) -> AsyncIterator[str]:
        held = _parse(seen)
        deadline = time.monotonic() + self._lifetime_s
        yield f"retry: {RETRY_MS}\n\n"
        while True:
            parts = await self._render()
            if parts is None:
                return
            changed = [name for name, html in parts.items() if held.get(name) != _digest(html)]
            if changed:
                held = {name: _digest(html) for name, html in parts.items()}
                current = event_id(parts)
                for name in changed:
                    yield _event(name, current, parts[name])
            if time.monotonic() >= deadline:
                return
            await anyio.sleep(self._poll_s)


def _digest(html: str) -> str:
    return hashlib.sha256(html.encode()).hexdigest()[:16]


def _parse(seen: str | None) -> dict[str, str]:
    held: dict[str, str] = {}
    for pair in (seen or "").split(","):
        name, _, digest = pair.partition(":")
        if name and digest:
            held[name] = digest
    return held


def _event(name: str, current: str, html: str) -> str:
    data = "".join(f"data: {line}\n" for line in html.splitlines() or [""])
    return f"event: {name}\nid: {current}\n{data}\n"

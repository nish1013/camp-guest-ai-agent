import pytest

from camp_agent.http.status_events import RETRY_MS, StatusEvents, event_id

pytestmark = pytest.mark.anyio

FIRST = {"status": "<p>Received</p>", "actions": "<form>step-up</form>"}
WORKING = {"status": "<p>Maintenance is working on it</p>", "actions": FIRST["actions"]}


class Renders:
    def __init__(self, *snapshots: dict[str, str] | None) -> None:
        self._snapshots = list(snapshots)

    async def __call__(self) -> dict[str, str] | None:
        return self._snapshots.pop(0) if self._snapshots else None


async def events(renders: Renders, seen: str | None = None) -> list[str]:
    stream = StatusEvents(renders, poll_s=0, lifetime_s=60).stream(seen)
    return [chunk async for chunk in stream]


def names(chunks: list[str]) -> list[str]:
    return [chunk.split("\n")[0] for chunk in chunks[1:]]


async def test_us9_first_connect_sends_all() -> None:
    chunks = await events(Renders(FIRST))

    assert chunks[0] == f"retry: {RETRY_MS}\n\n"
    assert names(chunks) == ["event: status", "event: actions"]


async def test_us9_page_render_not_resent() -> None:
    assert names(await events(Renders(FIRST, FIRST), seen=event_id(FIRST))) == []


async def test_us9_status_change_sent_alone() -> None:
    chunks = await events(Renders(FIRST, FIRST, WORKING), seen=event_id(FIRST))

    assert names(chunks) == ["event: status"]
    assert f"id: {event_id(WORKING)}\n" in chunks[1]
    assert "data: <p>Maintenance is working on it</p>\n\n" in chunks[1]


async def test_us9_reconnect_skips_held_parts() -> None:
    first = await events(Renders(FIRST, WORKING))
    last_id = first[-1].split("id: ")[1].split("\n")[0]

    again = await events(Renders(WORKING), seen=last_id)

    assert last_id == event_id(WORKING)
    assert names(again) == []


async def test_us9_garbled_seen_sends_all() -> None:
    assert len(names(await events(Renders(FIRST), seen="x,::,status"))) == 2


async def test_us9_multiline_framed() -> None:
    chunks = await events(Renders({"status": "<p>a</p>\n<p>b</p>"}))

    assert chunks[1].endswith("data: <p>a</p>\ndata: <p>b</p>\n\n")


async def test_us9_stream_ends_at_lifetime() -> None:
    stream = StatusEvents(Renders(FIRST, WORKING), poll_s=0, lifetime_s=0).stream(None)

    assert names([chunk async for chunk in stream]) == ["event: status", "event: actions"]

import re
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests.fakes import FakeClock
from tests.integration.intake_support import send

SEEN = re.compile(r'sse-connect="(/c/[^/"]+)/events\?seen=([^"]+)"')


def hold(db: Engine, reason: str, held_at: str) -> None:
    with db.begin() as conn:
        conn.execute(
            text("UPDATE cases SET state = 'held', state_reason = :r, held_at = :at"),
            {"r": reason, "at": held_at},
        )


def events(client: TestClient, url: str, **headers: str) -> str:
    response = client.get(url, headers=headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    return response.text


def stream_url(page: str) -> str:
    found = SEEN.search(page)
    assert found is not None
    return f"{found[1]}/events?seen={found[2]}"


def test_us9_case_link_opens_case(client: TestClient) -> None:
    token = send(client, "where is the pool").cookies["case_token"]
    client.cookies.clear()

    page = client.get(f"/c/{token}")

    assert page.status_code == 200
    assert "Received" in page.text
    assert f'name="offered" value="{token}"' in page.text
    assert page.cookies["case_token"] == token


def test_us9_unknown_case_404(client: TestClient) -> None:
    token = send(client, "where is the pool").cookies["case_token"]

    forged = client.get(f"/c/{token[:-1]}x")
    unknown = client.get("/c/unknown")

    assert (forged.status_code, unknown.status_code) == (404, 404)
    assert forged.text == unknown.text
    assert client.get("/c/unknown/events").status_code == 404


def test_us9_stream_sends_status(client: TestClient) -> None:
    token = send(client, "where is the pool").cookies["case_token"]

    stream = events(client, f"/c/{token}/events")

    assert "event: status\n" in stream
    assert "event: actions\n" in stream
    assert "data: <p>Status: <strong data-status>Received</strong></p>\n" in stream


def test_us9_page_render_not_resent(client: TestClient) -> None:
    send(client, "where is the pool")

    assert "event:" not in events(client, stream_url(client.get("/").text))


def test_us9_status_change_pushed(client: TestClient, db: Engine) -> None:
    send(client, "I want a refund")
    url = stream_url(client.get("/").text)

    hold(db, "money", "2026-10-19T13:00:00+00:00")
    stream = events(client, url)

    assert "event: status\n" in stream
    assert "Waiting on reception" in stream
    assert "event: actions\n" not in stream


def test_us9_reconnect_uses_last_event_id(client: TestClient, db: Engine) -> None:
    token = send(client, "I want a refund").cookies["case_token"]
    hold(db, "money", "2026-10-19T13:00:00+00:00")
    last = events(client, f"/c/{token}/events").split("id: ")[1].split("\n")[0]

    again = events(client, f"/c/{token}/events?seen=stale", **{"Last-Event-ID": last})

    assert "event:" not in again


def test_d30_held_at_night(client: TestClient, db: Engine, clock: FakeClock) -> None:
    clock.advance(timedelta(hours=9, minutes=10))
    send(client, "I want a refund")
    hold(db, "money", "2026-10-19T22:10:00+00:00")

    assert "Reception opens at 08:00." in client.get("/").text

    clock.advance(timedelta(hours=8, minutes=50))
    assert "Waiting on reception" in client.get("/").text

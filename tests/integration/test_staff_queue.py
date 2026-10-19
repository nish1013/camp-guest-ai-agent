from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tests.fakes import FakeClock
from tests.integration.staff_support import DEFAULTS, insert_case, login, queue_order


def test_us11_no_session_goes_to_login(client: TestClient) -> None:
    for path in ("/staff/cases", "/staff/cases/parked"):
        reply = client.get(path, follow_redirects=False)

        assert reply.status_code == 303
        assert reply.headers["location"] == "/staff/login"


def test_us11_wrong_password_refused(client: TestClient) -> None:
    reply = client.post("/staff/login", data={"user": DEFAULTS.staff_user, "password": "guess"})

    assert reply.status_code == 401
    assert "Wrong user name or password." in reply.text
    assert client.get("/staff/cases", follow_redirects=False).status_code == 303


def test_us11_login_then_logout(client: TestClient) -> None:
    reply = login(client)

    assert reply.status_code == 303
    assert reply.headers["location"] == "/staff/cases"
    assert client.get("/staff/cases").status_code == 200

    client.post("/staff/logout")
    assert client.get("/staff/cases", follow_redirects=False).status_code == 303


def test_us11_urgent_first_then_oldest(client: TestClient, db: Engine, clock: FakeClock) -> None:
    now = clock.now()
    can_wait = insert_case(db, urgency="can_wait", created_at=now - timedelta(hours=3))
    normal_old = insert_case(db, created_at=now - timedelta(hours=2))
    normal_new = insert_case(db, created_at=now - timedelta(hours=1))
    urgent = insert_case(db, urgency="urgent", created_at=now)
    login(client)

    page = client.get("/staff/cases").text

    ids = [can_wait, normal_old, normal_new, urgent]
    assert queue_order(page, ids) == [urgent, normal_old, normal_new, can_wait]


@pytest.mark.parametrize(("minutes", "overdue"), [(14, False), (16, True)])
def test_us11_held_14_00_overdue_at_14_16(
    client: TestClient, db: Engine, clock: FakeClock, minutes: int, overdue: bool
) -> None:
    held_at = clock.now()
    older = insert_case(db, created_at=held_at - timedelta(hours=1))
    held = insert_case(db, "held", "money", held_at=held_at, created_at=held_at)
    clock.advance(timedelta(minutes=minutes))
    login(client)

    page = client.get("/staff/cases").text

    assert ("data-overdue" in page) is overdue
    assert queue_order(page, [older, held])[0] == (held if overdue else older)


def test_us11_parked_list_shows_reason(client: TestClient, db: Engine) -> None:
    spam = insert_case(db, "parked", "spam")
    unverified = insert_case(db, "parked", "verification")
    open_case = insert_case(db)
    login(client)

    page = client.get("/staff/cases/parked").text
    queue = client.get("/staff/cases").text

    assert f'data-case="{spam}"' in page and f'data-case="{unverified}"' in page
    assert f'data-case="{open_case}"' not in page
    assert page.count("data-reason>spam<") == 1
    assert page.count("data-reason>verification<") == 1
    assert f'data-case="{spam}"' not in queue

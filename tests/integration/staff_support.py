from datetime import datetime
from uuid import uuid4

from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import Engine, text

from camp_agent.config import Settings

DEFAULTS = Settings()


def login(client: TestClient) -> Response:
    return client.post(
        "/staff/login",
        data={"user": DEFAULTS.staff_user, "password": DEFAULTS.staff_password.get_secret_value()},
        follow_redirects=False,
    )


def insert_case(
    db: Engine,
    state: str = "open",
    reason: str | None = None,
    urgency: str = "normal",
    held_at: datetime | None = None,
    created_at: datetime | None = None,
    safety: bool = False,
) -> int:
    with db.begin() as conn:
        case_id: int = conn.execute(
            text(
                "INSERT INTO cases (case_token, state, state_reason, urgency, held_at, safety,"
                " created_at) VALUES (:token, :state, :reason, :urgency, :held_at, :safety,"
                " coalesce(:created_at, now())) RETURNING id"
            ),
            {
                "token": uuid4().hex,
                "state": state,
                "reason": reason,
                "urgency": urgency,
                "held_at": held_at,
                "safety": safety,
                "created_at": created_at,
            },
        ).scalar_one()
    return case_id


def queue_order(page: str, case_ids: list[int]) -> list[int]:
    return sorted(case_ids, key=lambda case_id: page.index(f'data-case="{case_id}"'))

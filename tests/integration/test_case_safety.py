import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

INSERT = text(
    "INSERT INTO cases (case_token, state, state_reason, safety, urgency, held_at)"
    " VALUES ('k1', :state, :reason, true, :urgency, :held_at)"
)
HELD_AT = "2026-10-19T14:00:00Z"


def test_i9_safety_case_urgent_held(db: Engine) -> None:
    with db.begin() as conn:
        conn.execute(
            INSERT,
            {"state": "held", "reason": "emergency", "urgency": "urgent", "held_at": HELD_AT},
        )


@pytest.mark.parametrize(
    "row",
    [
        {"state": "parked", "reason": "spam", "urgency": "urgent", "held_at": None},
        {"state": "held", "reason": "emergency", "urgency": "normal", "held_at": HELD_AT},
        {"state": "open", "reason": None, "urgency": "can_wait", "held_at": None},
    ],
    ids=["parked", "held-normal", "open-can-wait"],
)
def test_i9_safety_check_rejects(db: Engine, row: dict[str, str | None]) -> None:
    with pytest.raises(IntegrityError, match="ck_cases_safety"), db.begin() as conn:
        conn.execute(INSERT, row)

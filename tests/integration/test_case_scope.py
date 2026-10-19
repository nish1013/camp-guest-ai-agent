import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

INSERT = text(
    "INSERT INTO cases (case_token, scope_cabin, scope_stay_from, scope_stay_to, scope_source)"
    " VALUES (:token, :cabin, :stay_from, :stay_to, :source)"
)
STAY = {"stay_from": "2026-10-18", "stay_to": "2026-10-25"}


@pytest.mark.parametrize("source", ["qr", "step_up", "staff"])
def test_i7_scope_with_known_source(db: Engine, source: str) -> None:
    with db.begin() as conn:
        conn.execute(INSERT, {"token": "k1", "cabin": "C12", "source": source, **STAY})


def test_i7_no_scope_no_source(db: Engine) -> None:
    with db.begin() as conn:
        conn.execute(
            INSERT,
            {"token": "k1", "cabin": None, "source": None, "stay_from": None, "stay_to": None},
        )


@pytest.mark.parametrize(
    "row",
    [
        {"cabin": "C12", "source": None, **STAY},
        {"cabin": "C12", "source": "email", **STAY},
        {"cabin": None, "source": "qr", **STAY},
        {"cabin": "C12", "source": "qr", "stay_from": None, "stay_to": "2026-10-25"},
    ],
    ids=["no-source", "unknown-source", "source-no-cabin", "no-stay-from"],
)
def test_i7_scope_must_name_source(db: Engine, row: dict[str, str | None]) -> None:
    with pytest.raises(IntegrityError, match="ck_cases_scope_source"), db.begin() as conn:
        conn.execute(INSERT, {"token": "k1", **row})

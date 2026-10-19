from datetime import date

import pytest

from camp_agent.domain.scope import Scope, ScopeSource
from camp_agent.qr.qr_token import QrOutcome, QrTokens

TOKENS = QrTokens("test-secret")
C12 = TOKENS.issue("C12", date(2026, 10, 18), date(2026, 10, 25))


def test_us1_valid_token_gives_scope() -> None:
    reading = TOKENS.read(C12, date(2026, 10, 19))

    assert reading.outcome is QrOutcome.VALID
    assert reading.scope == Scope("C12", date(2026, 10, 18), date(2026, 10, 25), ScopeSource.QR)


@pytest.mark.parametrize(
    ("today", "outcome"),
    [
        (date(2026, 10, 17), QrOutcome.VALID),
        (date(2026, 10, 25), QrOutcome.VALID),
        (date(2026, 10, 26), QrOutcome.EXPIRED),
    ],
)
def test_us1_expires_after_stay_end(today: date, outcome: QrOutcome) -> None:
    assert TOKENS.read(C12, today).outcome is outcome


def test_us1_ended_stay_has_no_scope() -> None:
    ended = TOKENS.issue("C12", date(2026, 10, 10), date(2026, 10, 17))

    assert TOKENS.read(ended, date(2026, 10, 19)).scope is None


@pytest.mark.parametrize(
    "token",
    [
        QrTokens("other-secret").issue("C12", date(2026, 10, 18), date(2026, 10, 25)),
        C12[:-2] + ("AA" if not C12.endswith("AA") else "BB"),
        "not-a-token",
        "",
    ],
    ids=["other-key", "tampered", "garbage", "empty"],
)
def test_us1_bad_signature_is_invalid(token: str) -> None:
    reading = TOKENS.read(token, date(2026, 10, 19))

    assert reading.outcome is QrOutcome.INVALID
    assert reading.scope is None


def test_us1_signed_bad_payload_invalid() -> None:
    serializer = TOKENS._serializer
    reversed_stay = serializer.dumps({"c": "C12", "f": "2026-10-25", "t": "2026-10-18"})
    missing_cabin = serializer.dumps({"f": "2026-10-18", "t": "2026-10-25"})

    assert TOKENS.read(reversed_stay, date(2026, 10, 19)).outcome is QrOutcome.INVALID
    assert TOKENS.read(missing_cabin, date(2026, 10, 19)).outcome is QrOutcome.INVALID

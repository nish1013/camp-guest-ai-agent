from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from camp_agent.qr.qr_token import QrTokens
from tests.integration.intake_support import SECRET, audit, count, rows, send

C12 = QrTokens(SECRET).issue("C12", date(2026, 10, 18), date(2026, 10, 25))
FORGED = QrTokens("other-secret").issue("C12", date(2026, 10, 18), date(2026, 10, 25))


def test_us6_rate_limit_skips_safety(triage_client: TestClient, db: Engine) -> None:
    for i in range(20):
        send(triage_client, f"question {i}")
    assert send(triage_client, "where is the pool").status_code == 429

    response = send(triage_client, "fire")

    assert response.status_code == 200
    assert count(db, "messages") == 21
    assert rows(db, "SELECT kind FROM tasks WHERE kind = 'emergency'") == [("emergency",)]


def test_d3_masked_in_store_and_audit(triage_client: TestClient, db: Engine) -> None:
    send(triage_client, "my ref is BK-48213, call 07700 900123")

    masked = "my ref is [ref], call [phone]"
    assert rows(db, "SELECT text FROM messages") == [(masked,)]
    assert rows(db, "SELECT detail->>'input' FROM audit_entries WHERE step = 'verify'") == [
        (masked,)
    ]
    assert "48213" not in str(rows(db, "SELECT detail FROM audit_entries"))


def test_us1_bad_signature_audited(triage_client: TestClient, db: Engine) -> None:
    triage_client.get(f"/q/{FORGED}")

    send(triage_client, "where is the pool")
    send(triage_client, "and the gym?")

    assert audit(db).count(("qr_scope", "invalid_token")) == 1


def test_us1_valid_scan_clears_bad_flag(triage_client: TestClient, db: Engine) -> None:
    triage_client.get(f"/q/{FORGED}")
    triage_client.get(f"/q/{C12}")

    send(triage_client, "where is the pool")

    assert ("qr_scope", "invalid_token") not in audit(db)

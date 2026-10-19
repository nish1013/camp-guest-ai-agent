import time
from concurrent.futures import Future, ThreadPoolExecutor
from uuid import uuid4

from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import Connection, Engine, text

from tests.integration.intake_support import RecordingGraph, count, send

LOCK_WAITERS = text(
    "SELECT count(*) FROM pg_stat_activity"
    " WHERE wait_event_type = 'Lock' AND datname = current_database()"
)


def wait_until_both_block(db: Engine, requests: list[Future[Response]]) -> None:
    deadline = time.monotonic() + 10
    with db.connect() as conn:
        while conn.execute(LOCK_WAITERS).scalar_one() < len(requests):
            if all(r.done() for r in requests) or time.monotonic() > deadline:
                return
            conn.rollback()
            time.sleep(0.02)


def hold_key(db: Engine, conn: Connection, key: str) -> None:
    with db.begin() as setup:
        case_id = setup.execute(
            text("INSERT INTO cases (case_token) VALUES ('blocker') RETURNING id")
        ).scalar_one()
    conn.execute(
        text("INSERT INTO messages (idempotency_key, case_id, text) VALUES (:key, :case_id, '')"),
        {"key": key, "case_id": case_id},
    )


def test_i1_parallel_retry_one_message(
    client: TestClient, db: Engine, graph: RecordingGraph
) -> None:
    key = str(uuid4())
    with db.connect() as blocker, ThreadPoolExecutor(2) as pool:
        hold_key(db, blocker, key)
        requests = [pool.submit(send, client, "no hot water", key) for _ in range(2)]
        wait_until_both_block(db, requests)
        blocker.rollback()
        first, second = (request.result(timeout=10) for request in requests)

    assert (first.status_code, second.status_code) == (200, 200)
    assert first.cookies["case_token"] == second.cookies["case_token"]
    assert count(db, "messages") == 1
    assert count(db, "cases WHERE case_token <> 'blocker'") == 1
    assert graph.batches == [["no hot water"]]

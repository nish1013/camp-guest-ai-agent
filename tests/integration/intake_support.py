from uuid import uuid4

from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import Engine, text

from camp_agent.graph.triage import BatchOutcome, PendingMessage

SECRET = "test-secret"


class RecordingGraph:
    def __init__(self) -> None:
        self.batches: list[list[str]] = []

    async def resume(self, case_id: int) -> None:
        pass

    async def run(self, case_id: int, batch: list[PendingMessage]) -> BatchOutcome:
        self.batches.append([message.text for message in batch])
        return BatchOutcome.TRIAGED


def send(client: TestClient, message: str, key: str | None = None) -> Response:
    return client.post("/messages", data={"text": message, "idempotency_key": key or str(uuid4())})


def count(db: Engine, table: str) -> int:
    with db.connect() as conn:
        found: int = conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
    return found


def rows(db: Engine, query: str) -> list[tuple[object, ...]]:
    with db.connect() as conn:
        return [tuple(row) for row in conn.execute(text(query))]


def audit(db: Engine) -> list[tuple[object, ...]]:
    return rows(db, "SELECT step, decision FROM audit_entries ORDER BY id")

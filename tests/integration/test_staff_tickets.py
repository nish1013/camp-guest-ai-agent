from collections.abc import Iterator
from datetime import timedelta
from uuid import uuid4

import anyio
import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import Engine, text
from sqlalchemy.ext.asyncio import AsyncEngine

from camp_agent.app import create_app
from camp_agent.config import Settings
from camp_agent.db.pg_triage_store import PgTriageStore
from camp_agent.db.task_repository import TaskRepository
from camp_agent.db.ticket_lock import lock_ticket, unlock_ticket
from camp_agent.domain.audit_entry import AuditEntry
from camp_agent.domain.route_guard import TaskState
from camp_agent.domain.ticket_status import TicketStatus
from camp_agent.graph.triage_types import StepRecord, TaskTransition, TicketLink
from camp_agent.intake.apply_ticket_status import ApplyTicketStatus
from camp_agent.ticket.demo_ticket_status import DemoTicketStatus
from camp_agent.ticket.ticket_types import TicketStatusChanged
from tests.fakes import FakeClock, SwitchableGuide, SwitchableStays
from tests.integration.intake_support import SECRET, RecordingGraph, rows
from tests.integration.staff_support import login
from tests.integration.test_fault_races import wait_for

WORKING = "Maintenance is working on it"


def ticketed_case(db: Engine, status: str = "open", state: str = "open") -> tuple[int, str]:
    token = uuid4().hex
    with db.begin() as conn:
        case_id: int = conn.execute(
            text(
                "INSERT INTO cases (case_token, state, scope_cabin, scope_stay_from,"
                " scope_stay_to, scope_source, closed_at) VALUES (:token, :state, 'C12',"
                " '2026-10-18', '2026-10-25', 'qr', CASE WHEN :state = 'closed' THEN now() END)"
                " RETURNING id"
            ),
            {"token": token, "state": state},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO tasks (case_id, step_id, kind, category, urgency, state, summary,"
                " fault_type, cabin, ticket_ref, ticket_status, ticket_version)"
                " VALUES (:case_id, 'm1/t0', 'fault', 'maintenance', 'normal', 'ticketed',"
                " 'heater broken', 'heating', 'C12', 'T1', :status, 1)"
            ),
            {"case_id": case_id, "status": status},
        )
    return case_id, token


def demo_ticket(db: Engine) -> None:
    with db.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO demo_tickets (case_id, step_id, cabin, team, fault_type, urgency,"
                " summary, status, version) VALUES (1, 'm1/t0', 'C12', 'maintenance', 'heating',"
                " 'normal', 'heater broken', 'open', 1)"
            )
        )


def set_status(client: TestClient, status: str, ref: str = "T1") -> Response:
    return client.post(
        f"/staff/tickets/{ref}/status", data={"status": status}, follow_redirects=False
    )


def task_status(db: Engine) -> list[tuple[object, ...]]:
    return rows(db, "SELECT case_id, ticket_status, ticket_version FROM tasks ORDER BY case_id")


def test_us13_in_progress_reaches_guest(client: TestClient, db: Engine) -> None:
    case_id, token = ticketed_case(db)
    demo_ticket(db)
    login(client)

    reply = set_status(client, "in_progress")

    assert reply.status_code == 303
    assert task_status(db) == [(case_id, "in_progress", 2)]
    assert rows(db, "SELECT step, decision FROM audit_entries") == [
        ("ticket_status", "in_progress")
    ]
    assert rows(db, "SELECT count(*) FROM ticket_events") == [(0,)]
    client.cookies.set("case_token", token)
    assert WORKING in client.get("/").text


def test_us13_linked_cases_both_done(client: TestClient, db: Engine) -> None:
    k1, _ = ticketed_case(db)
    k2, token = ticketed_case(db)
    demo_ticket(db)
    login(client)

    set_status(client, "done")

    assert task_status(db) == [(k1, "done", 2), (k2, "done", 2)]
    assert rows(db, "SELECT state FROM cases ORDER BY id") == [("closed",), ("closed",)]
    client.cookies.set("case_token", token)
    assert "heater broken</em>: Done" in client.get("/").text


def test_us13_done_with_booking_confirmed_closes(client: TestClient, db: Engine) -> None:
    case_id, _ = ticketed_case(db)
    demo_ticket(db)
    with db.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO tasks (case_id, step_id, kind, urgency, state, summary, cabin,"
                " booking_party, booking_date, booking_time) VALUES (:case_id, 'm1/t1', 'table',"
                " 'normal', :state, 'table for 4', 'C12', 4, '2026-10-19', '19:30')"
            ),
            {"case_id": case_id, "state": "booking_requested"},
        )
    login(client)

    set_status(client, "done")
    assert rows(db, "SELECT state FROM cases") == [("open",)]

    with db.begin() as conn:
        conn.execute(text("UPDATE tasks SET state = 'booking_confirmed' WHERE step_id = 'm1/t1'"))
    set_status(client, "cancelled")

    assert rows(db, "SELECT state FROM cases") == [("closed",)]


def test_i11_ticket_reopened_reopens_case(client: TestClient, db: Engine) -> None:
    ticketed_case(db, status="done", state="closed")
    demo_ticket(db)
    login(client)

    set_status(client, "in_progress")

    assert rows(db, "SELECT state, closed_at FROM cases") == [("open", None)]


def test_i12_busy_case_waits_in_outbox(client: TestClient, db: Engine, clock: FakeClock) -> None:
    ticketed_case(db)
    demo_ticket(db)
    with db.begin() as conn:
        conn.execute(
            text("UPDATE cases SET run_lease_owner = gen_random_uuid(), run_lease_until = :until"),
            {"until": clock.now() + timedelta(seconds=60)},
        )
    login(client)

    set_status(client, "in_progress")
    assert task_status(db)[0][1:] == ("open", 1)
    assert rows(db, "SELECT status, version FROM ticket_events") == [("in_progress", 2)]

    clock.advance(timedelta(seconds=61))
    set_status(client, "done")

    assert task_status(db)[0][1:] == ("done", 3)
    assert rows(db, "SELECT count(*) FROM ticket_events") == [(0,)]


@pytest.mark.parametrize(("ref", "code"), [("T99", 404), ("X1", 404)])
def test_us13_unknown_ticket_404(client: TestClient, ref: str, code: int) -> None:
    login(client)

    assert set_status(client, "done", ref).status_code == code


def test_us13_bad_status_422(client: TestClient, db: Engine) -> None:
    demo_ticket(db)
    login(client)

    assert set_status(client, "booked").status_code == 422


def test_us13_needs_login(client: TestClient) -> None:
    assert set_status(client, "done").status_code == 303


@pytest.mark.anyio
async def test_i12_events_v3_v2_v3(db: Engine, async_db: AsyncEngine, clock: FakeClock) -> None:
    case_id, _ = ticketed_case(db)
    with db.begin() as conn:
        for status, version in (("done", 3), ("in_progress", 2), ("done", 3)):
            conn.execute(
                text(
                    "INSERT INTO ticket_events (ticket_ref, status, version) VALUES ('T1', :s, :v)"
                ),
                {"s": status, "v": version},
            )

    await ApplyTicketStatus(async_db, clock).handle_pending()

    assert task_status(db) == [(case_id, "done", 3)]
    assert rows(db, "SELECT step, decision FROM audit_entries") == [("ticket_status", "done")]
    assert rows(db, "SELECT state FROM cases") == [("closed",)]
    assert rows(db, "SELECT count(*) FROM ticket_events") == [(0,)]


@pytest.fixture
def polling_client(
    db: Engine,
    migrated_url: str,
    clock: FakeClock,
    guide: SwitchableGuide,
    stays: SwitchableStays,
) -> Iterator[TestClient]:
    settings = Settings(database_url=migrated_url, secret_key=SECRET, outbox_poll_s=0.05)
    app = create_app(settings, clock=clock, graph=RecordingGraph(), guide=guide, stays=stays)
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.anyio
async def test_d45_poller_applies_outbox(
    polling_client: TestClient, db: Engine, async_db: AsyncEngine
) -> None:
    case_id, _ = ticketed_case(db)
    demo_ticket(db)

    event = await DemoTicketStatus(async_db).set("T1", TicketStatus.IN_PROGRESS)

    assert event == TicketStatusChanged("T1", TicketStatus.IN_PROGRESS, 2)
    with anyio.fail_after(5):
        while task_status(db) != [(case_id, "in_progress", 2)]:
            await anyio.sleep(0.05)


@pytest.mark.anyio
async def test_i12_event_before_task_kept(
    db: Engine, async_db: AsyncEngine, clock: FakeClock
) -> None:
    demo_ticket(db)
    await DemoTicketStatus(async_db).set("T1", TicketStatus.IN_PROGRESS)
    handler = ApplyTicketStatus(async_db, clock)

    await handler.handle_pending()
    assert rows(db, "SELECT count(*) FROM ticket_events") == [(1,)]

    case_id, _ = ticketed_case(db)
    await handler.handle_pending()

    assert task_status(db) == [(case_id, "in_progress", 2)]
    assert rows(db, "SELECT count(*) FROM ticket_events") == [(0,)]


def queued_fault(db: Engine) -> int:
    with db.begin() as conn:
        case_id: int = conn.execute(
            text(
                "INSERT INTO cases (case_token, state, scope_cabin, scope_stay_from,"
                " scope_stay_to, scope_source) VALUES (:token, 'open', 'C12', '2026-10-18',"
                " '2026-10-25', 'qr') RETURNING id"
            ),
            {"token": uuid4().hex},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO tasks (case_id, step_id, kind, category, urgency, state, summary,"
                " fault_type) VALUES (:case_id, 'm1/t0', 'fault', 'maintenance', 'normal',"
                " 'drafting', 'heater broken', 'heating')"
            ),
            {"case_id": case_id},
        )
    return case_id


@pytest.mark.anyio
async def test_i12_link_waits_for_status_pass(db: Engine, async_db: AsyncEngine) -> None:
    k1, _ = ticketed_case(db)
    k2 = queued_fault(db)
    # Read by the link step before the pass below applied version 2.
    seen = TicketLink("T1", TicketStatus.OPEN, 1, "C12")
    move = TaskTransition("m1/t0", TaskState.TICKETED, TaskState.DRAFTING, ticket=seen)
    step = StepRecord(AuditEntry("link", "linked"), transitions=(move,))

    async with async_db.connect() as holder:
        await lock_ticket(holder, "T1")
        await holder.commit()
        async with anyio.create_task_group() as tg:
            tg.start_soon(PgTriageStore(async_db).commit, k2, step)
            with anyio.move_on_after(2):
                await wait_for(async_db, 1)
            # The pass listed only K1 and applies version 2 to it while holding the lock.
            async with async_db.begin() as conn:
                event = TicketStatusChanged("T1", TicketStatus.DONE, 2)
                await TaskRepository(conn).apply_ticket_status(k1, event)
            await unlock_ticket(holder, "T1")
            await holder.commit()

    assert task_status(db) == [(k1, "done", 2), (k2, "done", 2)]

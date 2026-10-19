from dataclasses import replace
from typing import cast

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from camp_agent.db.pg_triage_store import PgTriageStore
from camp_agent.domain.audit_entry import AuditEntry
from camp_agent.domain.case_state import CaseState, StateReason
from camp_agent.domain.case_status import CaseStatus
from camp_agent.domain.route_guard import TaskKind, TaskState
from camp_agent.domain.urgency import Urgency
from camp_agent.graph.triage_types import StepRecord, TaskDraft
from tests.fakes import oct_19
from tests.integration.intake_support import count

pytestmark = pytest.mark.anyio

TASK = TaskDraft("m1/t0", TaskKind.MONEY, None, Urgency.NORMAL, TaskState.HELD, "refund")
GUARD = AuditEntry("route_guard", "money")


def new_case(db: Engine) -> int:
    with db.begin() as conn:
        case_id: int = conn.execute(
            text("INSERT INTO cases (case_token) VALUES ('k1') RETURNING id")
        ).scalar_one()
    return case_id


async def test_i13_step_saves_audit_with_change(db: Engine, async_db: AsyncEngine) -> None:
    store = PgTriageStore(async_db)
    case_id = new_case(db)
    held = CaseStatus().hold(StateReason.MONEY, oct_19().now())

    await store.commit(case_id, StepRecord(GUARD, held, (TASK,)))

    assert (await store.load(case_id)).status == held
    assert (count(db, "tasks"), count(db, "audit_entries")) == (1, 1)


async def test_i13_failed_step_leaves_no_audit(db: Engine, async_db: AsyncEngine) -> None:
    store = PgTriageStore(async_db)
    case_id = new_case(db)
    held = CaseStatus().hold(StateReason.MONEY, oct_19().now())
    bad = replace(TASK, kind=cast(TaskKind, "refund"))

    with pytest.raises(IntegrityError, match="ck_tasks_kind"):
        await store.commit(case_id, StepRecord(GUARD, held, (bad,)))

    assert (await store.load(case_id)).status.state is CaseState.OPEN
    assert (count(db, "tasks"), count(db, "audit_entries")) == (0, 0)


async def test_i3_rerun_step_keeps_one_task(db: Engine, async_db: AsyncEngine) -> None:
    store = PgTriageStore(async_db)
    case_id = new_case(db)

    await store.commit(case_id, StepRecord(GUARD, tasks=(TASK,)))
    await store.commit(case_id, StepRecord(GUARD, tasks=(TASK,)))

    assert count(db, "tasks") == 1

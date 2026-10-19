import pytest
from fastapi.testclient import TestClient
from markupsafe import escape
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from camp_agent.domain.citation_check import GUIDE_DOWN, NO_INFORMATION
from camp_agent.llm.llm_types import GuideAnswer
from tests.fakes import FakeLlm, SwitchableGuide, demo_section
from tests.integration.intake_support import audit, rows, send

POOL = "When does the pool open?"
SAUNA = "Is there a sauna?"
RECEPTION = demo_section("reception").body
CITED = FakeLlm(answers={POOL: GuideAnswer(text="08:00-20:00", section_id="pool-hours")})
INVENTED = FakeLlm(answers={SAUNA: GuideAnswer(text="Sauna 09:00-17:00", section_id="spa-hours")})


def tasks(db: Engine) -> list[tuple[object, ...]]:
    return rows(db, "SELECT kind, state, answer, answer_section FROM tasks")


@pytest.mark.parametrize("llm", [CITED], ids=["cited"])
def test_us3_answer_cites_section(triage_client: TestClient, db: Engine) -> None:
    send(triage_client, POOL)

    page = triage_client.get("/").text
    assert tasks(db) == [("question", "done", "08:00-20:00", "pool-hours")]
    assert "08:00-20:00" in page
    assert "<span data-cited>pool-hours</span>" in page
    assert audit(db)[-1] == ("answer", "cited")


def test_us3_no_section_gives_reception(triage_client: TestClient, db: Engine) -> None:
    send(triage_client, SAUNA)

    assert tasks(db) == [("question", "done", f"{NO_INFORMATION} {RECEPTION}", None)]
    assert escape(f"{NO_INFORMATION} {RECEPTION}") in triage_client.get("/").text


@pytest.mark.parametrize("llm", [INVENTED], ids=["spa-hours"])
def test_us3_missing_section_withheld(triage_client: TestClient, db: Engine) -> None:
    send(triage_client, SAUNA)

    page = triage_client.get("/").text
    assert tasks(db) == [("question", "done", f"{NO_INFORMATION} {RECEPTION}", None)]
    assert "09:00-17:00" not in page
    assert rows(
        db, "SELECT decision, detail->>'proposed' FROM audit_entries WHERE step = 'answer'"
    ) == [("withheld", "spa-hours")]


def test_d42_guide_down_gives_reception(
    triage_client: TestClient, db: Engine, guide: SwitchableGuide
) -> None:
    guide.down = True

    send(triage_client, POOL)

    assert escape(f"{GUIDE_DOWN} {RECEPTION}") in triage_client.get("/").text
    assert audit(db)[-1] == ("answer", "guide_down")


def test_us3_answer_only_on_question(db: Engine) -> None:
    with pytest.raises(IntegrityError, match="ck_tasks_answer"), db.begin() as conn:
        case_id = conn.execute(
            text("INSERT INTO cases (case_token, state) VALUES ('k1', 'open') RETURNING id")
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO tasks (case_id, step_id, kind, urgency, state, summary, answer)"
                " VALUES (:case_id, 'm1/t0', 'fault', 'urgent', 'queued', 'leak', 'fixed')"
            ),
            {"case_id": case_id},
        )

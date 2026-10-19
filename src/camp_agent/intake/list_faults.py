from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncEngine

from camp_agent.db.report_repository import ReportRepository
from camp_agent.db.task_repository import TaskRepository
from camp_agent.domain.fault_flow import Confirmation, batch_of
from camp_agent.domain.guest_status import LOGGED, same_question, split_question
from camp_agent.domain.route_guard import TaskState
from camp_agent.domain.specialist import specialist_for
from camp_agent.intake.answer_types import CaseFaults, QuestionView, TicketLine


class ListFaults:
    def __init__(self, engine: AsyncEngine, camp_timezone: ZoneInfo) -> None:
        self._engine = engine
        self._tz = camp_timezone

    async def __call__(self, case_id: int) -> CaseFaults:
        tickets: list[TicketLine] = []
        questions: list[QuestionView] = []
        split: dict[str, list[str]] = {}
        async with self._engine.connect() as conn:
            for fault in await TaskRepository(conn).faults(case_id):
                team = specialist_for(fault.category)
                if fault.state is TaskState.TICKETED and team is not None:
                    tickets.append(TicketLine(fault.summary, LOGGED[team]))
                elif fault.state is TaskState.AWAITING_SPLIT:
                    split.setdefault(batch_of(fault.step_id), []).append(fault.summary)
                elif fault.state is TaskState.AWAITING_SAME and fault.same_report_id is not None:
                    earlier = await ReportRepository(conn).get(fault.same_report_id)
                    at = f"{earlier.at.astimezone(self._tz):%H:%M}"
                    text = same_question(earlier.fault_type, at)
                    questions.append(QuestionView(Confirmation.SAME, fault.step_id, text))
        questions[:0] = [
            QuestionView(Confirmation.SPLIT, batch, split_question(summaries))
            for batch, summaries in split.items()
        ]
        return CaseFaults(tickets, questions)

from dataclasses import dataclass
from pathlib import Path

from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from camp_agent.clock import Clock
from camp_agent.db.cases import CaseRecord
from camp_agent.db.tasks import AnsweredQuestion
from camp_agent.domain.cases import DeskHours
from camp_agent.domain.guest_status import QuickPick, guest_status
from camp_agent.guide.port import GuideCopy
from camp_agent.http.status_events import event_id
from camp_agent.intake.case_view import (
    BookingLine,
    CaseFaults,
    ListAnswers,
    ListBookings,
    ListDeclined,
    ListFaults,
)
from camp_agent.intake.step_up import StepUpForm

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
templates.env.globals["picks"] = list(QuickPick)


STATUS = "status"
ACTIONS = "actions"


@dataclass(frozen=True)
class CaseView:
    link: str
    status: str
    answers: list[AnsweredQuestion]
    faults: CaseFaults
    bookings: list[BookingLine]
    declined: list[str]
    step_up: bool


@dataclass(frozen=True)
class CasePanel:
    link: str
    lines: Markup
    actions: Markup
    seen: str


class CasePanels:
    # The one place a case becomes what the guest sees: the page, the stream and the notices.
    def __init__(
        self,
        clock: Clock,
        desk: DeskHours,
        guide_copy: GuideCopy,
        list_answers: ListAnswers,
        list_faults: ListFaults,
        list_bookings: ListBookings,
        list_declined: ListDeclined,
        step_up_form: StepUpForm,
    ) -> None:
        self._clock = clock
        self._desk = desk
        self._guide_copy = guide_copy
        self._list_answers = list_answers
        self._list_faults = list_faults
        self._list_bookings = list_bookings
        self._list_declined = list_declined
        self._step_up_form = step_up_form

    async def panel(self, case: CaseRecord) -> CasePanel:
        parts = await self.parts(case)
        return CasePanel(
            f"/c/{case.case_token}",
            Markup(parts[STATUS]),
            Markup(parts[ACTIONS]),
            event_id(parts),
        )

    async def parts(self, case: CaseRecord) -> dict[str, str]:
        view = await self._view(case)
        return {
            STATUS: templates.get_template("_case_lines.html").render(case=view),
            ACTIONS: templates.get_template("_case_actions.html").render(case=view),
        }

    async def _view(self, case: CaseRecord) -> CaseView:
        now = self._clock.now()
        return CaseView(
            link=f"/c/{case.case_token}",
            status=guest_status(
                case.status,
                self._guide_copy.emergency,
                self._guide_copy.reception,
                None if self._desk.is_open(now) else self._desk.opens,
            ),
            answers=await self._list_answers(case.id),
            faults=await self._list_faults(case.id),
            bookings=await self._list_bookings(case.id),
            declined=await self._list_declined(case.id),
            step_up=await self._step_up_form.shown(case),
        )

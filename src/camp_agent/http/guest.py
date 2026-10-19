import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import StringConstraints

from camp_agent.clock import Clock
from camp_agent.config import Settings
from camp_agent.db.answered_question import AnsweredQuestion
from camp_agent.db.case_record import CaseRecord
from camp_agent.domain.guest_status import (
    BOOKING_FOUND,
    BOOKINGS_DOWN,
    NO_BOOKING_MATCH,
    guest_status,
)
from camp_agent.domain.scope import Scope
from camp_agent.guide.guide_types import GuideCopy
from camp_agent.intake.find_open_case import FindOpenCase
from camp_agent.intake.intake_types import Accepted, SubmitMessageCommand
from camp_agent.intake.list_answers import ListAnswers
from camp_agent.intake.run_coordinator import RunCoordinator
from camp_agent.intake.step_up_form import StepUpForm
from camp_agent.intake.step_up_types import StepUpCommand, StepUpResult
from camp_agent.intake.submit_message import SubmitMessage
from camp_agent.intake.submit_step_up import SubmitStepUp
from camp_agent.qr.qr_token import QrOutcome, QrTokens

CASE_COOKIE = "case_token"
QR_SESSION_KEY = "qr_token"
QR_INVALID_KEY = "qr_invalid"
CABIN_HINT_KEY = "cabin_hint"
RATE_LIMITED_REPLY = "Please try again in a few minutes"

MessageText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
]
CabinHint = Annotated[str, StringConstraints(strip_whitespace=True, max_length=16)]
Surname = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
BookingRef = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]


@dataclass(frozen=True)
class CaseView:
    link: str
    status: str
    answers: list[AnsweredQuestion]
    step_up: bool


@dataclass(frozen=True)
class GuestServices:
    settings: Settings
    clock: Clock
    guide_copy: GuideCopy
    qr_tokens: QrTokens
    submit: SubmitMessage
    find_open_case: FindOpenCase
    list_answers: ListAnswers
    coordinator: RunCoordinator
    step_up: SubmitStepUp
    step_up_form: StepUpForm


log = logging.getLogger(__name__)
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
router = APIRouter()


def get_services(request: Request) -> GuestServices:
    services: GuestServices = request.app.state.guest_services
    return services


Services = Annotated[GuestServices, Depends(get_services)]


@router.get("/", response_class=HTMLResponse)
async def home(request: Request, services: Services) -> HTMLResponse:
    return await _page(request, services)


@router.get("/q/{qr_token}", response_class=HTMLResponse)
async def open_from_qr(request: Request, qr_token: str, services: Services) -> HTMLResponse:
    reading = services.qr_tokens.read(qr_token, services.clock.today())
    if reading.outcome is QrOutcome.VALID:
        request.session[QR_SESSION_KEY] = qr_token
    else:
        request.session.pop(QR_SESSION_KEY, None)
    if reading.outcome is QrOutcome.INVALID:
        log.warning("invalid QR token")
        # No case exists yet, so the audit entry is written on the case of the next message.
        request.session[QR_INVALID_KEY] = True
    else:
        request.session.pop(QR_INVALID_KEY, None)
    return await _page(request, services)


@router.post("/messages", response_class=HTMLResponse)
async def submit_message(
    request: Request,
    background: BackgroundTasks,
    services: Services,
    text: Annotated[MessageText, Form()],
    idempotency_key: Annotated[UUID, Form()],
    cabin_hint: Annotated[CabinHint, Form()] = "",
) -> HTMLResponse:
    if cabin_hint:
        request.session[CABIN_HINT_KEY] = cabin_hint
    result = await services.submit(
        SubmitMessageCommand(
            text=text,
            idempotency_key=idempotency_key,
            case_token=request.cookies.get(CASE_COOKIE),
            scope=_scope(request, services),
            client_ip=_client_ip(request),
            qr_invalid=bool(request.session.get(QR_INVALID_KEY)),
        )
    )
    if not isinstance(result, Accepted):
        return templates.TemplateResponse(
            request,
            "_reply.html",
            {"reply": RATE_LIMITED_REPLY},
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )
    if not result.replayed:
        request.session.pop(QR_INVALID_KEY, None)
        background.add_task(services.coordinator.drive, result.case.id)
    response = templates.TemplateResponse(
        request,
        "_case.html",
        {
            "case": await _view(result.case, services),
            "scope": _scope(request, services),
            "next_key": uuid4(),
        },
    )
    response.set_cookie(
        CASE_COOKIE,
        result.case.case_token,
        max_age=services.settings.case_cookie_max_age_s,
        httponly=True,
        samesite="lax",
        secure=services.settings.cookie_secure,
    )
    return response


@router.post("/c/{case_token}/step-up", response_class=HTMLResponse)
async def step_up(
    request: Request,
    background: BackgroundTasks,
    services: Services,
    case_token: str,
    surname: Annotated[Surname, Form()],
    booking_ref: Annotated[BookingRef, Form()],
) -> HTMLResponse:
    reply = await services.step_up(
        StepUpCommand(
            case_token=case_token,
            surname=surname,
            booking_ref=booking_ref,
            cabin_hint=request.session.get(CABIN_HINT_KEY),
            client_ip=_client_ip(request),
        )
    )
    if reply is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if reply.result is StepUpResult.MATCHED:
        background.add_task(services.coordinator.drive, reply.case.id)
    # Every outcome is a 200, so the status code says nothing about why a step-up failed (D2).
    return templates.TemplateResponse(
        request,
        "_case_status.html",
        {
            "case": await _view(reply.case, services),
            "reply": _step_up_reply(reply.result, services),
        },
    )


async def _page(request: Request, services: GuestServices) -> HTMLResponse:
    case = None
    token = request.cookies.get(CASE_COOKIE)
    if token is not None:
        case = await services.find_open_case(token)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "scope": _scope(request, services),
            "case": None if case is None else await _view(case, services),
            "next_key": uuid4(),
        },
    )


def _scope(request: Request, services: GuestServices) -> Scope | None:
    token = request.session.get(QR_SESSION_KEY)
    if token is None:
        return None
    return services.qr_tokens.read(token, services.clock.today()).scope


async def _view(case: CaseRecord, services: GuestServices) -> CaseView:
    return CaseView(
        link=f"/c/{case.case_token}",
        status=guest_status(
            case.status, services.guide_copy.emergency, services.guide_copy.reception
        ),
        answers=await services.list_answers(case.id),
        step_up=await services.step_up_form.shown(case),
    )


def _step_up_reply(result: StepUpResult, services: GuestServices) -> str | None:
    match result:
        case StepUpResult.MATCHED:
            return BOOKING_FOUND
        case StepUpResult.NO_MATCH:
            return NO_BOOKING_MATCH
        case StepUpResult.BOOKINGS_DOWN:
            return f"{BOOKINGS_DOWN} {services.guide_copy.reception}"
        case StepUpResult.LOCKED | StepUpResult.ALREADY_SCOPED:
            return None


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"

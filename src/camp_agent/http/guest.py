import logging
from dataclasses import dataclass
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Form,
    Header,
    HTTPException,
    Request,
    status,
)
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import StringConstraints

from camp_agent.clock import Clock
from camp_agent.config import Settings
from camp_agent.domain.fault_flow import Confirmation
from camp_agent.domain.guest_status import (
    BOOKING_FOUND,
    BOOKINGS_DOWN,
    NO_BOOKING_MATCH,
)
from camp_agent.domain.quick_pick import QuickPick
from camp_agent.domain.scope import Scope
from camp_agent.guide.guide_types import GuideCopy
from camp_agent.http.case_panels import CasePanels
from camp_agent.http.page_templates import templates
from camp_agent.http.status_events import StatusEvents
from camp_agent.intake.answer_types import AnswerCommand
from camp_agent.intake.find_case import FindCase
from camp_agent.intake.intake_types import Accepted, SubmitMessageCommand
from camp_agent.intake.run_coordinator import RunCoordinator
from camp_agent.intake.step_up_types import StepUpCommand, StepUpResult
from camp_agent.intake.submit_answer import SubmitAnswer
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
Subject = Annotated[str, StringConstraints(pattern=r"^m\d+(/t\d+)?$", max_length=40)]
CaseToken = Annotated[str, StringConstraints(min_length=1, max_length=64)]
Target = Literal["case", "new"]


@dataclass(frozen=True)
class CaseOffer:
    token: str
    label: str


@dataclass(frozen=True)
class GuestServices:
    settings: Settings
    clock: Clock
    guide_copy: GuideCopy
    qr_tokens: QrTokens
    submit: SubmitMessage
    find_case: FindCase
    panels: CasePanels
    coordinator: RunCoordinator
    step_up: SubmitStepUp
    answer: SubmitAnswer


log = logging.getLogger(__name__)
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


@router.get("/c/{case_token}", response_class=HTMLResponse)
async def case_page(request: Request, case_token: str, services: Services) -> HTMLResponse:
    case = await services.find_case(case_token)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    response = await _page(request, services, case_token)
    _keep_case(response, case_token, services)
    return response


@router.get("/c/{case_token}/events")
async def case_events(
    case_token: str,
    services: Services,
    seen: str | None = None,
    last_event_id: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    if await services.find_case(case_token) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)

    async def render() -> dict[str, str] | None:
        case = await services.find_case(case_token)
        return None if case is None else await services.panels.parts(case)

    events = StatusEvents(
        render, services.settings.status_poll_s, services.settings.status_stream_s
    )
    # A reconnect sends the id of the last event it got; the page link names its first render.
    return StreamingResponse(
        events.stream(last_event_id or seen),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/messages", response_class=HTMLResponse)
async def submit_message(
    request: Request,
    background: BackgroundTasks,
    services: Services,
    text: Annotated[MessageText, Form()],
    idempotency_key: Annotated[UUID, Form()],
    cabin_hint: Annotated[CabinHint, Form()] = "",
    pick: Annotated[QuickPick | None, Form()] = None,
    target: Annotated[Target | None, Form()] = None,
    offered: Annotated[CaseToken | None, Form()] = None,
) -> HTMLResponse:
    if target == "case" and offered is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT)
    if cabin_hint:
        request.session[CABIN_HINT_KEY] = cabin_hint
    result = await services.submit(
        SubmitMessageCommand(
            text=text,
            idempotency_key=idempotency_key,
            case_token=_case_to_join(request, target, offered),
            scope=_scope(request, services),
            client_ip=_client_ip(request),
            qr_invalid=bool(request.session.get(QR_INVALID_KEY)),
            pick=pick,
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
            "case": await services.panels.panel(result.case),
            "scope": _scope(request, services),
            "offer": await _offer(result.case.case_token, services),
            "next_key": uuid4(),
        },
    )
    _keep_case(response, result.case.case_token, services)
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
            "case": await services.panels.panel(reply.case),
            "reply": _step_up_reply(reply.result, services),
        },
    )


@router.post("/c/{case_token}/answer", response_class=HTMLResponse)
async def answer(
    request: Request,
    background: BackgroundTasks,
    services: Services,
    case_token: str,
    confirmation: Annotated[Confirmation, Form()],
    subject: Annotated[Subject, Form()],
    answer: Annotated[Literal["yes", "no"], Form()],
) -> HTMLResponse:
    reply = await services.answer(
        AnswerCommand(case_token, confirmation, subject, yes=answer == "yes")
    )
    if reply is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if reply.moved:
        background.add_task(services.coordinator.drive, reply.case.id)
    return templates.TemplateResponse(
        request, "_case_status.html", {"case": await services.panels.panel(reply.case)}
    )


async def _page(
    request: Request, services: GuestServices, case_token: str | None = None
) -> HTMLResponse:
    case = None
    offer = None
    token = case_token or request.cookies.get(CASE_COOKIE)
    if token is not None:
        case = await services.find_case(token)
        offer = await _offer(token, services)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "scope": _scope(request, services),
            "case": None if case is None else await services.panels.panel(case),
            "offer": offer,
            "next_key": uuid4(),
        },
    )


def _case_to_join(request: Request, target: Target | None, offered: str | None) -> str | None:
    # The form names the case it offered, so a second tab that opened a new case since does
    # not redirect the message. With no choice made, the cookie case is joined (D20).
    if target == "new":
        return None
    if target == "case":
        return offered
    return request.cookies.get(CASE_COOKIE)


async def _offer(case_token: str, services: GuestServices) -> CaseOffer | None:
    case = await services.find_case.open(case_token)
    if case is None:
        return None
    label = "your request" if case.scope is None else case.scope.cabin
    return CaseOffer(case.case_token, label)


def _scope(request: Request, services: GuestServices) -> Scope | None:
    token = request.session.get(QR_SESSION_KEY)
    if token is None:
        return None
    return services.qr_tokens.read(token, services.clock.today()).scope


def _keep_case(response: HTMLResponse, case_token: str, services: GuestServices) -> None:
    response.set_cookie(
        CASE_COOKIE,
        case_token,
        max_age=services.settings.case_cookie_max_age_s,
        httponly=True,
        samesite="lax",
        secure=services.settings.cookie_secure,
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

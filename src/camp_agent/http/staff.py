import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from camp_agent.config import Settings
from camp_agent.domain.faults import TicketStatus
from camp_agent.domain.routing import Category, Urgency
from camp_agent.intake.runs import RunCoordinator
from camp_agent.intake.tickets import ApplyTicketStatus
from camp_agent.staff.bookings import BookingDecision, SetBookingStatus
from camp_agent.staff.case_lock import StaffConflictError
from camp_agent.staff.queue import ListQueue, ShowCase
from camp_agent.staff.resolve import ResolveAsHuman, ResolveCommand, ResolveError
from camp_agent.staff.restore import RestoreCase, RestoreCommand, RestoreError
from camp_agent.stay.port import StayError
from camp_agent.ticket.demo_tickets import DemoTicketStatus

STAFF_SESSION_KEY = "staff"
LOGIN_PATH = "/staff/login"


def credentials_match(settings: Settings, user: str, password: str) -> bool:
    user_ok = secrets.compare_digest(user.encode(), settings.staff_user.encode())
    expected = settings.staff_password.get_secret_value().encode()
    password_ok = secrets.compare_digest(password.encode(), expected)
    return user_ok and password_ok


def require_staff(request: Request) -> None:
    # Open intake stops at the staff view and its approvals (D9).
    if not request.session.get(STAFF_SESSION_KEY):
        raise HTTPException(status.HTTP_303_SEE_OTHER, headers={"Location": LOGIN_PATH})


QUEUE_PATH = "/staff/cases"
LOGIN_REFUSED = "Wrong user name or password."
CASE_CHANGED = "This case changed since you opened it. It has been reloaded."
BOOKINGS_DOWN = "The booking system cannot be reached. Try again shortly."

Version = Annotated[int, Form(ge=0)]
BookingRef = Annotated[str, Form(max_length=40)]
StepId = Annotated[str | None, Form(pattern=r"^m\d+/(t\d+|emergency)$", max_length=40)]


@dataclass(frozen=True)
class StaffServices:
    settings: Settings
    camp_timezone: ZoneInfo
    queue: ListQueue
    show_case: ShowCase
    booking_status: SetBookingStatus
    resolve: ResolveAsHuman
    restore: RestoreCase
    coordinator: RunCoordinator
    tickets: DemoTicketStatus
    ticket_status: ApplyTicketStatus


templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
router = APIRouter(prefix="/staff")
guarded = APIRouter(dependencies=[Depends(require_staff)])


def get_services(request: Request) -> StaffServices:
    services: StaffServices = request.app.state.staff_services
    return services


Services = Annotated[StaffServices, Depends(get_services)]


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "staff_login.html", {})


@router.post("/login", response_model=None)
async def login(
    request: Request,
    services: Services,
    user: Annotated[str, Form(max_length=100)],
    password: Annotated[str, Form(max_length=200)],
) -> HTMLResponse | RedirectResponse:
    if not credentials_match(services.settings, user, password):
        return templates.TemplateResponse(
            request,
            "staff_login.html",
            {"error": LOGIN_REFUSED},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    request.session[STAFF_SESSION_KEY] = True
    return _to_queue()


@router.post("/logout")
async def logout(request: Request) -> RedirectResponse:
    request.session.pop(STAFF_SESSION_KEY, None)
    return RedirectResponse(LOGIN_PATH, status_code=status.HTTP_303_SEE_OTHER)


@guarded.get("/cases", response_class=HTMLResponse)
async def queue(request: Request, services: Services) -> HTMLResponse:
    context = {"items": await services.queue(), "tz": services.camp_timezone}
    return templates.TemplateResponse(request, "staff_queue.html", context)


@guarded.get("/cases/parked", response_class=HTMLResponse)
async def parked(request: Request, services: Services) -> HTMLResponse:
    context = {"cases": await services.queue.parked(), "tz": services.camp_timezone}
    return templates.TemplateResponse(request, "staff_parked.html", context)


@guarded.get("/cases/{case_id}", response_class=HTMLResponse)
async def case_page(request: Request, services: Services, case_id: int) -> HTMLResponse:
    return await _case_page(request, services, case_id)


@guarded.post("/bookings/{task_id}/status", response_model=None)
async def booking_status(
    request: Request,
    services: Services,
    task_id: int,
    decision: Annotated[Literal["confirm", "decline"], Form()],
    version: Version,
) -> HTMLResponse | RedirectResponse:
    command = BookingDecision(task_id, version, confirm=decision == "confirm")
    try:
        case_id = await services.booking_status(command)
    except StaffConflictError as conflict:
        return await _conflict(request, services, conflict)
    if case_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return _to_case(case_id)


@guarded.post("/cases/{case_id}/resolve", response_model=None)
async def resolve(
    request: Request,
    background: BackgroundTasks,
    services: Services,
    case_id: int,
    action: Annotated[Literal["approve", "reject"], Form()],
    version: Version,
    step_id: StepId = None,
    category: Annotated[Category | None, Form()] = None,
    urgency: Annotated[Urgency | None, Form()] = None,
) -> HTMLResponse | RedirectResponse:
    command = ResolveCommand(case_id, version, action == "approve", step_id, category, urgency)
    try:
        found = await services.resolve(command)
    except StaffConflictError as conflict:
        return await _conflict(request, services, conflict)
    except ResolveError as error:
        return await _case_page(
            request, services, case_id, str(error), status.HTTP_422_UNPROCESSABLE_CONTENT
        )
    if not found:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    # An approved fault or table goes back into its lane, which a run picks up.
    background.add_task(services.coordinator.drive, case_id)
    return _to_case(case_id)


@guarded.post("/cases/{case_id}/restore", response_model=None)
async def restore(
    request: Request,
    background: BackgroundTasks,
    services: Services,
    case_id: int,
    version: Version,
    booking_ref: BookingRef = "",
) -> HTMLResponse | RedirectResponse:
    command = RestoreCommand(case_id, version, booking_ref.strip() or None)
    try:
        found = await services.restore(command)
    except StaffConflictError as conflict:
        return await _conflict(request, services, conflict)
    except RestoreError as error:
        return await _case_page(
            request, services, case_id, str(error), status.HTTP_422_UNPROCESSABLE_CONTENT
        )
    except StayError:
        return await _case_page(
            request, services, case_id, BOOKINGS_DOWN, status.HTTP_503_SERVICE_UNAVAILABLE
        )
    if not found:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    # Triage runs again over the messages the park stopped (D33).
    background.add_task(services.coordinator.drive, case_id)
    return _to_case(case_id)


@guarded.post("/tickets/{ticket_ref}/status")
async def ticket_status(
    background: BackgroundTasks,
    services: Services,
    ticket_ref: str,
    ticket_status: Annotated[TicketStatus, Form(alias="status")],
    case_id: Annotated[int | None, Form()] = None,
) -> RedirectResponse:
    # The demo ticket system: real adapters send the same event by webhook or polling (D10).
    if await services.tickets.set(ticket_ref, ticket_status) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    background.add_task(services.ticket_status.handle_pending)
    return _to_case(case_id) if case_id is not None else _to_queue()


def _to_queue() -> RedirectResponse:
    return RedirectResponse(QUEUE_PATH, status_code=status.HTTP_303_SEE_OTHER)


def _to_case(case_id: int) -> RedirectResponse:
    return RedirectResponse(f"{QUEUE_PATH}/{case_id}", status_code=status.HTTP_303_SEE_OTHER)


async def _conflict(
    request: Request, services: StaffServices, conflict: StaffConflictError
) -> HTMLResponse:
    case_id: int = conflict.args[0]
    return await _case_page(request, services, case_id, CASE_CHANGED, status.HTTP_409_CONFLICT)


async def _case_page(
    request: Request,
    services: StaffServices,
    case_id: int,
    notice: str | None = None,
    status_code: int = status.HTTP_200_OK,
) -> HTMLResponse:
    detail = await services.show_case(case_id)
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    context = {"detail": detail, "notice": notice, "tz": services.camp_timezone}
    return templates.TemplateResponse(request, "staff_case.html", context, status_code=status_code)


router.include_router(guarded)

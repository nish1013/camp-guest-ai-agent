from dataclasses import dataclass
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from camp_agent.config import Settings
from camp_agent.http.staff_auth import (
    LOGIN_PATH,
    STAFF_SESSION_KEY,
    credentials_match,
    require_staff,
)
from camp_agent.staff.list_queue import ListQueue
from camp_agent.staff.show_case import ShowCase

QUEUE_PATH = "/staff/cases"
LOGIN_REFUSED = "Wrong user name or password."


@dataclass(frozen=True)
class StaffServices:
    settings: Settings
    camp_timezone: ZoneInfo
    queue: ListQueue
    show_case: ShowCase


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
    return RedirectResponse(QUEUE_PATH, status_code=status.HTTP_303_SEE_OTHER)


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

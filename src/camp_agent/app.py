import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import timedelta
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from starlette.middleware.sessions import SessionMiddleware

from camp_agent.clock import Clock, SystemClock
from camp_agent.config import Settings
from camp_agent.db.engine import make_engine
from camp_agent.db.pg_triage_store import PgTriageStore
from camp_agent.db.probe import DatabaseProbe
from camp_agent.domain.desk_hours import DeskHours
from camp_agent.domain.safety_rule import SafetyRule
from camp_agent.graph.guide_answerer import GuideAnswerer
from camp_agent.graph.langgraph_triage import LangGraphTriage
from camp_agent.graph.triage_graph import TriageGraph
from camp_agent.graph.triage_types import TriagePolicy
from camp_agent.guide.guide_copy import copy_from_guide
from camp_agent.guide.guide_port import GuidePort
from camp_agent.guide.markdown_guide import MarkdownGuide
from camp_agent.http import guest, health, staff
from camp_agent.http.case_panels import CasePanels
from camp_agent.http.guest import GuestServices
from camp_agent.http.staff import StaffServices
from camp_agent.http.status_notifier import StatusNotifier
from camp_agent.intake.apply_ticket_status import ApplyTicketStatus
from camp_agent.intake.find_case import FindCase
from camp_agent.intake.list_answers import ListAnswers
from camp_agent.intake.list_bookings import ListBookings
from camp_agent.intake.list_declined import ListDeclined
from camp_agent.intake.list_faults import ListFaults
from camp_agent.intake.outbox_poller import OutboxPoller
from camp_agent.intake.rate_limiter import SlidingWindowLimiter
from camp_agent.intake.run_coordinator import RunCoordinator
from camp_agent.intake.step_up_form import StepUpForm
from camp_agent.intake.step_up_types import StepUpLimits
from camp_agent.intake.submit_answer import SubmitAnswer
from camp_agent.intake.submit_message import SubmitMessage
from camp_agent.intake.submit_step_up import SubmitStepUp
from camp_agent.llm.llm_port import LlmPort
from camp_agent.llm.pydantic_ai_llm import PydanticAiLlm
from camp_agent.llm.retrying_llm import RetryingLlm
from camp_agent.notification.log_notifications import LogNotifications
from camp_agent.notification.notification_port import NotificationPort
from camp_agent.qr.qr_token import QrTokens
from camp_agent.staff.list_queue import ListQueue
from camp_agent.staff.resolve_as_human import ResolveAsHuman
from camp_agent.staff.restore_case import RestoreCase
from camp_agent.staff.set_booking_status import SetBookingStatus
from camp_agent.staff.show_case import ShowCase
from camp_agent.stay.seed_stays import SeedStays
from camp_agent.stay.stay_port import StayContextPort
from camp_agent.ticket.demo_ticket_status import DemoTicketStatus
from camp_agent.ticket.demo_tickets import DemoTickets
from camp_agent.ticket.retrying_tickets import RetryingTickets
from camp_agent.ticket.ticket_port import TicketPort


def create_app(
    settings: Settings | None = None,
    clock: Clock | None = None,
    graph: TriageGraph | None = None,
    llm: LlmPort | None = None,
    guide: GuidePort | None = None,
    stays: StayContextPort | None = None,
    tickets: TicketPort | None = None,
    notifications: NotificationPort | None = None,
) -> FastAPI:
    resolved = settings or Settings()
    camp_tz = ZoneInfo(resolved.camp_timezone)
    resolved_clock = clock or SystemClock(camp_tz)
    desk = DeskHours(resolved.desk_opens, resolved.desk_closes, camp_tz)
    safety = SafetyRule(resolved.safety_terms)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        guide_port = guide or MarkdownGuide(resolved.guide_path)
        guide_copy = await copy_from_guide(guide_port)
        engine = make_engine(resolved)
        panels = CasePanels(
            resolved_clock,
            desk,
            guide_copy,
            ListAnswers(engine),
            ListFaults(engine, camp_tz),
            ListBookings(engine),
            ListDeclined(engine),
            StepUpForm(engine, resolved.step_up_case_failures),
        )
        watch = StatusNotifier(engine, panels, notifications or LogNotifications())
        limiter = SlidingWindowLimiter(
            resolved.rate_limit_messages, timedelta(seconds=resolved.rate_limit_window_s)
        )
        retrying_llm = RetryingLlm(
            llm or _openai_llm(resolved), resolved.llm_attempts, resolved.llm_retry_delay_s
        )
        triage = graph or LangGraphTriage(
            retrying_llm,
            PgTriageStore(engine, watch),
            resolved_clock,
            TriagePolicy(
                safety,
                frozenset(resolved.held_categories),
                resolved.clarify_max_rounds,
                ZoneInfo(resolved.camp_timezone),
            ),
            GuideAnswerer(retrying_llm, guide_port, guide_copy.reception),
            RetryingTickets(
                tickets or DemoTickets(engine),
                resolved.ticket_attempts,
                resolved.ticket_retry_delay_s,
            ),
        )
        limits = StepUpLimits(
            resolved.step_up_case_failures,
            resolved.step_up_ip_failures,
            timedelta(seconds=resolved.step_up_ip_window_s),
        )
        stay_port = stays or SeedStays(resolved.stays_path)
        coordinator = RunCoordinator(
            engine, triage, resolved_clock, timedelta(seconds=resolved.run_lease_s)
        )
        app.state.health_probe = DatabaseProbe(engine)
        app.state.guest_services = GuestServices(
            settings=resolved,
            clock=resolved_clock,
            guide_copy=guide_copy,
            qr_tokens=QrTokens(resolved.secret_key),
            submit=SubmitMessage(
                engine,
                limiter,
                resolved_clock,
                safety,
                timedelta(seconds=resolved.reopen_window_s),
            ),
            find_case=FindCase(engine),
            panels=panels,
            coordinator=coordinator,
            step_up=SubmitStepUp(engine, stay_port, resolved_clock, limits),
            answer=SubmitAnswer(engine, resolved_clock),
        )
        gate = timedelta(seconds=resolved.gate_timeout_s)
        ticket_status = ApplyTicketStatus(engine, resolved_clock, watch)
        app.state.staff_services = StaffServices(
            settings=resolved,
            camp_timezone=camp_tz,
            queue=ListQueue(engine, resolved_clock, desk, gate),
            show_case=ShowCase(engine, resolved_clock, desk, gate),
            booking_status=SetBookingStatus(engine, resolved_clock, watch),
            resolve=ResolveAsHuman(engine, resolved_clock, watch),
            restore=RestoreCase(engine, resolved_clock, stay_port, watch),
            coordinator=coordinator,
            tickets=DemoTicketStatus(engine),
            ticket_status=ticket_status,
        )
        poller = None
        if resolved.outbox_poll_s > 0:
            poller = asyncio.create_task(OutboxPoller(ticket_status, resolved.outbox_poll_s).run())
        yield
        if poller is not None:
            poller.cancel()
            with suppress(asyncio.CancelledError):
                await poller
        await engine.dispose()

    app = FastAPI(title="Camp Guest AI Agent", lifespan=lifespan)
    app.add_middleware(
        SessionMiddleware,
        secret_key=resolved.secret_key,
        same_site="lax",
        https_only=resolved.cookie_secure,
    )
    app.include_router(health.router)
    app.include_router(guest.router)
    app.include_router(staff.router)
    return app


def _openai_llm(settings: Settings) -> PydanticAiLlm:
    # With no key the app still starts; every LLM call fails and the case is held (D16).
    model: Model | str = f"openai:{settings.llm_model}"
    if settings.openai_api_key is not None:
        provider = OpenAIProvider(api_key=settings.openai_api_key.get_secret_value())
        model = OpenAIChatModel(settings.llm_model, provider=provider)
    return PydanticAiLlm(model, settings.llm_timeout_s)

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from camp_agent.clock import Clock, SystemClock
from camp_agent.config import Settings
from camp_agent.db.engine import make_engine
from camp_agent.db.probe import DatabaseProbe
from camp_agent.graph.stub_graph import StubGraph
from camp_agent.graph.triage_graph import TriageGraph
from camp_agent.http import guest, health
from camp_agent.http.guest import GuestServices
from camp_agent.intake.find_open_case import FindOpenCase
from camp_agent.intake.rate_limiter import SlidingWindowLimiter
from camp_agent.intake.run_coordinator import RunCoordinator
from camp_agent.intake.submit_message import SubmitMessage
from camp_agent.qr.qr_token import QrTokens


def create_app(
    settings: Settings | None = None,
    clock: Clock | None = None,
    graph: TriageGraph | None = None,
) -> FastAPI:
    resolved = settings or Settings()
    resolved_clock = clock or SystemClock(ZoneInfo(resolved.camp_timezone))
    resolved_graph = graph or StubGraph()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = make_engine(resolved)
        limiter = SlidingWindowLimiter(
            resolved.rate_limit_messages, timedelta(seconds=resolved.rate_limit_window_s)
        )
        app.state.health_probe = DatabaseProbe(engine)
        app.state.guest_services = GuestServices(
            settings=resolved,
            clock=resolved_clock,
            qr_tokens=QrTokens(resolved.secret_key),
            submit=SubmitMessage(engine, limiter, resolved_clock),
            find_open_case=FindOpenCase(engine),
            coordinator=RunCoordinator(
                engine, resolved_graph, resolved_clock, timedelta(seconds=resolved.run_lease_s)
            ),
        )
        yield
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
    return app

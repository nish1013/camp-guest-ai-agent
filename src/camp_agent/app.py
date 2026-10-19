from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
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
from camp_agent.domain.safety_rule import SafetyRule
from camp_agent.graph.guide_answerer import GuideAnswerer
from camp_agent.graph.langgraph_triage import LangGraphTriage
from camp_agent.graph.triage_graph import TriageGraph
from camp_agent.graph.triage_types import TriagePolicy
from camp_agent.guide.guide_copy import copy_from_guide
from camp_agent.guide.guide_port import GuidePort
from camp_agent.guide.markdown_guide import MarkdownGuide
from camp_agent.http import guest, health
from camp_agent.http.guest import GuestServices
from camp_agent.intake.find_open_case import FindOpenCase
from camp_agent.intake.list_answers import ListAnswers
from camp_agent.intake.rate_limiter import SlidingWindowLimiter
from camp_agent.intake.run_coordinator import RunCoordinator
from camp_agent.intake.step_up_form import StepUpForm
from camp_agent.intake.step_up_types import StepUpLimits
from camp_agent.intake.submit_message import SubmitMessage
from camp_agent.intake.submit_step_up import SubmitStepUp
from camp_agent.llm.llm_port import LlmPort
from camp_agent.llm.pydantic_ai_llm import PydanticAiLlm
from camp_agent.llm.retrying_llm import RetryingLlm
from camp_agent.qr.qr_token import QrTokens
from camp_agent.stay.seed_stays import SeedStays
from camp_agent.stay.stay_port import StayContextPort


def create_app(
    settings: Settings | None = None,
    clock: Clock | None = None,
    graph: TriageGraph | None = None,
    llm: LlmPort | None = None,
    guide: GuidePort | None = None,
    stays: StayContextPort | None = None,
) -> FastAPI:
    resolved = settings or Settings()
    resolved_clock = clock or SystemClock(ZoneInfo(resolved.camp_timezone))
    safety = SafetyRule(resolved.safety_terms)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        guide_port = guide or MarkdownGuide(resolved.guide_path)
        guide_copy = await copy_from_guide(guide_port)
        engine = make_engine(resolved)
        limiter = SlidingWindowLimiter(
            resolved.rate_limit_messages, timedelta(seconds=resolved.rate_limit_window_s)
        )
        retrying_llm = RetryingLlm(
            llm or _openai_llm(resolved), resolved.llm_attempts, resolved.llm_retry_delay_s
        )
        triage = graph or LangGraphTriage(
            retrying_llm,
            PgTriageStore(engine),
            resolved_clock,
            TriagePolicy(safety, frozenset(resolved.held_categories), resolved.clarify_max_rounds),
            GuideAnswerer(retrying_llm, guide_port, guide_copy.reception),
        )
        limits = StepUpLimits(
            resolved.step_up_case_failures,
            resolved.step_up_ip_failures,
            timedelta(seconds=resolved.step_up_ip_window_s),
        )
        stay_port = stays or SeedStays(resolved.stays_path)
        app.state.health_probe = DatabaseProbe(engine)
        app.state.guest_services = GuestServices(
            settings=resolved,
            clock=resolved_clock,
            guide_copy=guide_copy,
            qr_tokens=QrTokens(resolved.secret_key),
            submit=SubmitMessage(engine, limiter, resolved_clock, safety),
            find_open_case=FindOpenCase(engine),
            list_answers=ListAnswers(engine),
            coordinator=RunCoordinator(
                engine, triage, resolved_clock, timedelta(seconds=resolved.run_lease_s)
            ),
            step_up=SubmitStepUp(engine, stay_port, resolved_clock, limits),
            step_up_form=StepUpForm(engine, resolved.step_up_case_failures),
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


def _openai_llm(settings: Settings) -> PydanticAiLlm:
    # With no key the app still starts; every LLM call fails and the case is held (D16).
    model: Model | str = f"openai:{settings.llm_model}"
    if settings.openai_api_key is not None:
        provider = OpenAIProvider(api_key=settings.openai_api_key.get_secret_value())
        model = OpenAIChatModel(settings.llm_model, provider=provider)
    return PydanticAiLlm(model, settings.llm_timeout_s)

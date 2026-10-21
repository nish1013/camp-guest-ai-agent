from datetime import date

from camp_agent.config import Settings
from camp_agent.domain.routing import Category, Route, Scope, ScopeSource, Urgency
from camp_agent.domain.safety import SafetyRule
from camp_agent.graph.guide_answerer import GuideAnswerer
from camp_agent.graph.langgraph_triage import LangGraphTriage
from camp_agent.graph.triage import PendingMessage, TriagePolicy
from camp_agent.llm.port import Classification
from tests.fakes import (
    CAMP_TZ,
    FakeLlm,
    FakeTickets,
    InMemoryTriageStore,
    SwitchableGuide,
    demo_guide,
    oct_19,
)

DEFAULTS = Settings()
C12 = Scope("C12", date(2026, 10, 18), date(2026, 10, 25), ScopeSource.QR)
POLICY = TriagePolicy(
    SafetyRule(DEFAULTS.safety_terms),
    frozenset(DEFAULTS.held_categories),
    DEFAULTS.clarify_max_rounds,
    CAMP_TZ,
)
CASE = 1
RECEPTION = "Call reception on 01632 960123."


def proposal(category: Category, route: Route, urgency: Urgency) -> Classification:
    return Classification(category=category, route=route, urgency=urgency)


def new_store(scope: Scope | None = C12) -> InMemoryTriageStore:
    store = InMemoryTriageStore()
    store.add_case(CASE, scope)
    return store


def graph_for(
    llm: FakeLlm,
    store: InMemoryTriageStore,
    guide: SwitchableGuide | None = None,
    tickets: FakeTickets | None = None,
) -> LangGraphTriage:
    answerer = GuideAnswerer(llm, guide or demo_guide(), RECEPTION)
    return LangGraphTriage(llm, store, oct_19(), POLICY, answerer, tickets or FakeTickets())


async def triage(
    llm: FakeLlm,
    *texts: str,
    store: InMemoryTriageStore | None = None,
    guide: SwitchableGuide | None = None,
    tickets: FakeTickets | None = None,
) -> InMemoryTriageStore:
    store = store or new_store()
    graph = graph_for(llm, store, guide, tickets)
    for i, text in enumerate(texts, start=1):
        await graph.run(CASE, [PendingMessage(i, text)])
    return store


def steps(store: InMemoryTriageStore) -> list[str]:
    return [f"{entry.step}:{entry.decision}" for entry in store.audit]

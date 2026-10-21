from datetime import date, datetime
from zoneinfo import ZoneInfo

from camp_agent.config import Settings
from camp_agent.domain.routing import Scope, ScopeSource
from camp_agent.domain.safety import SafetyRule
from camp_agent.graph.triage import TriagePolicy

_DEFAULTS = Settings()
CAMP_TZ = ZoneInfo(_DEFAULTS.camp_timezone)
NOW = datetime(2026, 10, 19, 14, tzinfo=CAMP_TZ)
TODAY = NOW.date()
C12 = Scope("C12", date(2026, 10, 18), date(2026, 10, 25), ScopeSource.QR)
HELD_CATEGORIES = frozenset(_DEFAULTS.held_categories)
POLICY = TriagePolicy(
    SafetyRule(_DEFAULTS.safety_terms), HELD_CATEGORIES, _DEFAULTS.clarify_max_rounds, CAMP_TZ
)

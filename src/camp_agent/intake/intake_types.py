from dataclasses import dataclass
from uuid import UUID

from camp_agent.db.case_record import CaseRecord
from camp_agent.domain.quick_pick import QuickPick
from camp_agent.domain.scope import Scope


@dataclass(frozen=True)
class SubmitMessageCommand:
    text: str
    idempotency_key: UUID
    case_token: str | None
    scope: Scope | None
    client_ip: str
    qr_invalid: bool = False
    pick: QuickPick | None = None


@dataclass(frozen=True)
class Accepted:
    case: CaseRecord
    replayed: bool


@dataclass(frozen=True)
class RateLimited:
    pass


type SubmitResult = Accepted | RateLimited

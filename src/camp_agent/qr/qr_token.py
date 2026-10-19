from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from itsdangerous import BadSignature, URLSafeSerializer

from camp_agent.domain.scope import Scope, ScopeSource


class QrOutcome(StrEnum):
    VALID = "valid"
    EXPIRED = "expired"
    INVALID = "invalid"


@dataclass(frozen=True)
class QrReading:
    outcome: QrOutcome
    scope: Scope | None = None


class QrTokens:
    def __init__(self, secret_key: str) -> None:
        self._serializer = URLSafeSerializer(secret_key, salt="qr-scope")

    def issue(self, cabin: str, stay_from: date, stay_to: date) -> str:
        payload = {"c": cabin, "f": stay_from.isoformat(), "t": stay_to.isoformat()}
        token: str = self._serializer.dumps(payload)
        return token

    def read(self, token: str, today: date) -> QrReading:
        try:
            scope = self._scope(self._serializer.loads(token))
        except (BadSignature, KeyError, TypeError, ValueError):
            return QrReading(QrOutcome.INVALID)
        if today > scope.stay_to:
            return QrReading(QrOutcome.EXPIRED)
        return QrReading(QrOutcome.VALID, scope)

    def _scope(self, payload: dict[str, str]) -> Scope:
        stay_from = date.fromisoformat(payload["f"])
        stay_to = date.fromisoformat(payload["t"])
        if not payload["c"] or stay_from > stay_to:
            raise ValueError("malformed scope")
        return Scope(payload["c"], stay_from, stay_to, ScopeSource.QR)

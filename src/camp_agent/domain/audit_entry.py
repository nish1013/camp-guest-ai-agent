from collections.abc import Mapping
from dataclasses import dataclass, field

type AuditValue = str | int | list[str]


@dataclass(frozen=True)
class AuditEntry:
    step: str
    decision: str
    detail: Mapping[str, AuditValue] = field(default_factory=dict)

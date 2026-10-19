from dataclasses import dataclass


@dataclass(frozen=True)
class StatusNotice:
    case_id: int
    status: str

from enum import StrEnum


class Urgency(StrEnum):
    URGENT = "urgent"
    NORMAL = "normal"
    CAN_WAIT = "can_wait"


_RANK = {Urgency.CAN_WAIT: 0, Urgency.NORMAL: 1, Urgency.URGENT: 2}


def higher_urgency(a: Urgency, b: Urgency) -> Urgency:
    return a if _RANK[a] >= _RANK[b] else b


def urgency_rank(urgency: Urgency) -> int:
    return _RANK[urgency]

from datetime import datetime

from camp_agent.domain.urgency import Urgency, urgency_rank


def queue_rank(urgency: Urgency, overdue: bool, created_at: datetime) -> tuple[int, bool, datetime]:
    # Urgency orders the view (D8); within one urgency an overdue case goes first (D11).
    return (-urgency_rank(urgency), not overdue, created_at)

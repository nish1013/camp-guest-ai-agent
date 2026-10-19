from dataclasses import dataclass
from enum import StrEnum

from camp_agent.domain.ticket_status import CLOSED_TICKET_STATES, TicketStatus

CREATE_TICKET = "create_ticket"
SUMMARY_MAX = 200


class ValidationOutcome(StrEnum):
    PASS = "pass"
    BLOCK = "block"


class LinkDecision(StrEnum):
    LINK = "link"
    NEW_TICKET = "new_ticket"
    HOLD = "hold"


@dataclass(frozen=True)
class ArgsCheck:
    outcome: ValidationOutcome
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class LinkCheck:
    decision: LinkDecision
    reasons: tuple[str, ...] = ()


def check_ticket_args(tool: str, cabin: str, summary: str, scope_cabin: str) -> ArgsCheck:
    # Bad args are blocked, never corrected: a rewrite changes what the guest asked for (D15).
    reasons: list[str] = []
    if tool != CREATE_TICKET:
        reasons.append(f"tool must be {CREATE_TICKET}")
    if cabin != scope_cabin:
        reasons.append(f"cabin must be {scope_cabin}")
    if not summary.strip() or len(summary) > SUMMARY_MAX:
        reasons.append(f"summary must be 1 to {SUMMARY_MAX} characters")
    if reasons:
        return ArgsCheck(ValidationOutcome.BLOCK, tuple(reasons))
    return ArgsCheck(ValidationOutcome.PASS)


def check_link(
    ticket_ref: str | None, ticket_status: TicketStatus | None, cabin: str | None, scope_cabin: str
) -> LinkCheck:
    if ticket_ref is None or ticket_status is None:
        # The earlier report has no ticket yet; a second ticket would be the duplicate (D38).
        return LinkCheck(LinkDecision.HOLD, ("the earlier report has no ticket yet",))
    if cabin != scope_cabin:
        return LinkCheck(LinkDecision.HOLD, (f"cabin must be {scope_cabin}",))
    if ticket_status in CLOSED_TICKET_STATES:
        return LinkCheck(LinkDecision.NEW_TICKET, ("the earlier ticket is closed",))
    return LinkCheck(LinkDecision.LINK)

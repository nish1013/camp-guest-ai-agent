from dataclasses import dataclass
from datetime import date, datetime, time
from enum import StrEnum

from camp_agent.domain.scope import Scope
from camp_agent.domain.table_flow import TableBooking
from camp_agent.domain.ticket_status import CLOSED_TICKET_STATES, TicketStatus

CREATE_TICKET = "create_ticket"
REQUEST_TABLE = "request_table"
SUMMARY_MAX = 200
PARTY_MAX = 12


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
class TableCheck:
    outcome: ValidationOutcome
    reasons: tuple[str, ...] = ()
    booking: TableBooking | None = None


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


def check_table_args(
    tool: str,
    cabin: str,
    party: int | None,
    day: date | None,
    at: time | None,
    scope: Scope,
    now: datetime,
) -> TableCheck:
    # A detail the guest did not give is blocked, never filled in (D15).
    reasons: list[str] = []
    if tool != REQUEST_TABLE:
        reasons.append(f"tool must be {REQUEST_TABLE}")
    if cabin != scope.cabin:
        reasons.append(f"cabin must be {scope.cabin}")
    if party is None or not 1 <= party <= PARTY_MAX:
        reasons.append(f"party must be 1 to {PARTY_MAX}")
    if day is None or at is None:
        reasons.append("date and time must be given")
    elif not scope.stay_from <= day <= scope.stay_to:
        reasons.append(f"date must be from {scope.stay_from} to {scope.stay_to}")
    elif datetime.combine(day, at, now.tzinfo) <= now:
        reasons.append("time must be later than now")
    if reasons or party is None or day is None or at is None:
        return TableCheck(ValidationOutcome.BLOCK, tuple(reasons))
    return TableCheck(ValidationOutcome.PASS, booking=TableBooking(cabin, party, day, at))


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

from datetime import UTC, datetime, timedelta

from camp_agent.domain.case_state import CaseState, StateReason
from camp_agent.domain.case_status import CaseStatus
from camp_agent.domain.guest_status import NOT_VERIFIED, guest_status
from camp_agent.domain.urgency import Urgency

T0 = datetime(2026, 10, 19, 14, tzinfo=UTC)
T1 = T0 + timedelta(minutes=5)


def test_i9_emergency_is_urgent_held() -> None:
    status = CaseStatus(urgency=Urgency.CAN_WAIT).emergency(T0)

    assert (status.state, status.reason, status.safety, status.urgency, status.held_at) == (
        CaseState.HELD,
        StateReason.EMERGENCY,
        True,
        Urgency.URGENT,
        T0,
    )


def test_i9_safety_case_never_parked() -> None:
    status = CaseStatus().emergency(T0)

    assert status.park(StateReason.SPAM) == status


def test_d16_hold_keeps_first_reason() -> None:
    status = CaseStatus().hold(StateReason.MONEY, T0).hold(StateReason.LLM_FAILED, T1)

    assert (status.reason, status.held_at) == (StateReason.MONEY, T0)


def test_d8_emergency_overrides_hold() -> None:
    status = CaseStatus().hold(StateReason.MONEY, T0).emergency(T1)

    assert (status.reason, status.held_at) == (StateReason.EMERGENCY, T0)


def test_d32_third_unclear_holds() -> None:
    status = CaseStatus().clarify(2, T0).clarify(2, T0)
    assert (status.state, status.clarify_rounds) == (CaseState.OPEN, 2)

    held = status.clarify(2, T1)
    assert (held.state, held.reason, held.held_at) == (
        CaseState.HELD,
        StateReason.CLARIFY_LIMIT,
        T1,
    )


def test_d8_llm_never_lowers_urgency() -> None:
    status = CaseStatus().emergency(T0).raise_urgency(Urgency.CAN_WAIT)

    assert status.urgency is Urgency.URGENT


def test_i10_hold_keeps_park() -> None:
    parked = CaseStatus().park_unverified()

    assert parked.hold(StateReason.MONEY, T0) == parked


def test_i10_failed_step_up_parks_held() -> None:
    status = CaseStatus().hold(StateReason.MONEY, T0).park_unverified()

    assert (status.state, status.reason, status.held_at) == (
        CaseState.PARKED,
        StateReason.VERIFICATION,
        None,
    )


def test_i9_failed_step_up_keeps_safety_held() -> None:
    status = CaseStatus().emergency(T0)

    assert status.park_unverified() == status


def test_us7_parked_unverified_shows_reception() -> None:
    status = CaseStatus().park_unverified()

    assert guest_status(status, "Call 999.", "Call 01632.") == f"{NOT_VERIFIED} Call 01632."

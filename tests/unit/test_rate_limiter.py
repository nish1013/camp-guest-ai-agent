from datetime import UTC, datetime, timedelta

from camp_agent.intake.messages import SlidingWindowLimiter

T0 = datetime(2026, 10, 19, 14, tzinfo=UTC)
WINDOW = timedelta(minutes=10)


def fill(limiter: SlidingWindowLimiter, keys: list[str], count: int) -> list[bool]:
    return [limiter.allow(keys, T0 + timedelta(seconds=i)) for i in range(count)]


def test_us2_21st_in_window_refused() -> None:
    limiter = SlidingWindowLimiter(20, WINDOW)

    assert fill(limiter, ["ip:a"], 21) == [True] * 20 + [False]


def test_us2_allowed_once_window_passes() -> None:
    limiter = SlidingWindowLimiter(20, WINDOW)
    fill(limiter, ["ip:a"], 20)

    assert not limiter.allow(["ip:a"], T0 + WINDOW - timedelta(microseconds=1))
    assert limiter.allow(["ip:a"], T0 + WINDOW)


def test_us2_refusal_is_not_counted() -> None:
    limiter = SlidingWindowLimiter(2, WINDOW)
    fill(limiter, ["ip:a"], 2)
    for _ in range(5):
        limiter.allow(["ip:a"], T0 + timedelta(minutes=5))

    assert limiter.allow(["ip:a"], T0 + WINDOW + timedelta(seconds=1))


def test_us2_cabin_limit_spans_ips() -> None:
    limiter = SlidingWindowLimiter(20, WINDOW)
    for i in range(20):
        assert limiter.allow([f"ip:{i}", "cabin:C12"], T0)

    assert not limiter.allow(["ip:new", "cabin:C12"], T0)
    assert limiter.allow(["ip:new", "cabin:C14"], T0)


def test_us2_other_ip_not_limited() -> None:
    limiter = SlidingWindowLimiter(20, WINDOW)
    fill(limiter, ["ip:a"], 20)

    assert limiter.allow(["ip:b"], T0)

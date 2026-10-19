import pytest

from camp_agent.domain.pii_masker import mask_pii


@pytest.mark.parametrize(
    "text, masked",
    [
        ("my ref is BK-48213, call 07700 900123", "my ref is [ref], call [phone]"),
        ("ref BK 48213 please", "ref [ref] please"),
        ("ref bk48213", "ref [ref]"),
        ("mail anna.muller+camp@example.co.uk now", "mail [email] now"),
        ("call +44 7700 900123", "call [phone]"),
        ("call (01632) 960-123", "call [phone]"),
        ("table for 4 at 19:30", "table for 4 at 19:30"),
        ("cabin C12, 18.10.2026 to 25.10.2026", "cabin C12, 18.10.2026 to 25.10.2026"),
        ("code 1234 5678", "code 1234 5678"),
    ],
    ids=[
        "ref-and-phone",
        "ref-space",
        "ref-lower",
        "email",
        "intl-phone",
        "bracket-phone",
        "time-kept",
        "dates-kept",
        "8-digits-kept",
    ],
)
def test_d3_masker(text: str, masked: str) -> None:
    assert mask_pii(text) == masked

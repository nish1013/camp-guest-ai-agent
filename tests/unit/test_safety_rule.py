import pytest

from camp_agent.domain.safety import SafetyRule

RULE = SafetyRule(["fire", "gas", "smoke", "flood", "medical", "injury"])


@pytest.mark.parametrize(
    "text, hits",
    [
        ("smoke coming from the heater", ["smoke"]),
        ("FIRE", ["fire"]),
        ("gas smell lol", ["gas"]),
        ("the bathroom is flooding", ["flood"]),
        ("fires and smoke", ["fire", "smoke"]),
        ("where is the fireplace wood", []),
        ("no hot water", []),
    ],
    ids=["smoke", "upper", "gas", "flooding", "two", "fireplace", "none"],
)
def test_d8_safety_terms(text: str, hits: list[str]) -> None:
    assert RULE.hits(text) == hits


def test_d8_empty_terms_refused() -> None:
    with pytest.raises(ValueError, match="at least one term"):
        SafetyRule([])

import pytest

from camp_agent.domain.citation_check import (
    GUIDE_DOWN,
    NO_INFORMATION,
    AnswerOutcome,
    CheckedAnswer,
    check_citation,
    guide_down,
)

RECEPTION = "Call reception on 01632 960123."
OFFERED = frozenset({"pool-hours", "reception"})
NO_INFO = f"{NO_INFORMATION} {RECEPTION}"


@pytest.mark.parametrize(
    "text, proposed, expected",
    [
        (
            " 08:00-20:00 ",
            "pool-hours",
            CheckedAnswer(AnswerOutcome.CITED, "08:00-20:00", "pool-hours", "pool-hours"),
        ),
        ("", None, CheckedAnswer(AnswerOutcome.NO_SECTION, NO_INFO)),
        ("Yes, 09:00-17:00.", None, CheckedAnswer(AnswerOutcome.NO_SECTION, NO_INFO)),
        (
            "09:00-17:00",
            "spa-hours",
            CheckedAnswer(AnswerOutcome.WITHHELD, NO_INFO, proposed="spa-hours"),
        ),
        (
            "08:00-20:00",
            "Pool-Hours",
            CheckedAnswer(AnswerOutcome.WITHHELD, NO_INFO, proposed="Pool-Hours"),
        ),
        ("  ", "pool-hours", CheckedAnswer(AnswerOutcome.WITHHELD, NO_INFO, proposed="pool-hours")),
    ],
    ids=["cited", "no-section", "uncited-text", "missing-section", "case-differs", "empty-text"],
)
def test_d17_citation_check(text: str, proposed: str | None, expected: CheckedAnswer) -> None:
    assert check_citation(text, proposed, OFFERED, RECEPTION) == expected


def test_d42_guide_down_gives_reception() -> None:
    assert guide_down(RECEPTION) == CheckedAnswer(
        AnswerOutcome.GUIDE_DOWN, f"{GUIDE_DOWN} {RECEPTION}"
    )

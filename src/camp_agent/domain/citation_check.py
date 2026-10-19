from collections.abc import Set
from dataclasses import dataclass
from enum import StrEnum

NO_INFORMATION = "I don't have that information."
GUIDE_DOWN = "I can't check the guide right now."


class AnswerOutcome(StrEnum):
    CITED = "cited"
    NO_SECTION = "no_section"
    WITHHELD = "withheld"
    GUIDE_DOWN = "guide_down"


@dataclass(frozen=True)
class CheckedAnswer:
    outcome: AnswerOutcome
    text: str
    cited: str | None = None
    proposed: str | None = None


def check_citation(
    text: str, proposed: str | None, offered: Set[str], reception: str
) -> CheckedAnswer:
    # An answer stands only on a section the guide gave; anything else is withheld (D17).
    if proposed is None:
        return CheckedAnswer(AnswerOutcome.NO_SECTION, f"{NO_INFORMATION} {reception}")
    if proposed not in offered or not text.strip():
        return CheckedAnswer(
            AnswerOutcome.WITHHELD, f"{NO_INFORMATION} {reception}", proposed=proposed
        )
    return CheckedAnswer(AnswerOutcome.CITED, text.strip(), cited=proposed, proposed=proposed)


def guide_down(reception: str) -> CheckedAnswer:
    return CheckedAnswer(AnswerOutcome.GUIDE_DOWN, f"{GUIDE_DOWN} {reception}")

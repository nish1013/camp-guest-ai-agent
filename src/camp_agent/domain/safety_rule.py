import re
from collections.abc import Sequence


class SafetyRule:
    def __init__(self, terms: Sequence[str]) -> None:
        if not terms:
            raise ValueError("the safety rule needs at least one term")
        alternatives = "|".join(re.escape(term.strip()) for term in terms)
        self._pattern = re.compile(rf"\b({alternatives})(?:s|es|ed|ing)?\b", re.IGNORECASE)

    def hits(self, text: str) -> list[str]:
        return sorted({match.lower() for match in self._pattern.findall(text)})

from dataclasses import dataclass


@dataclass(frozen=True)
class AnsweredQuestion:
    question: str
    answer: str
    section_id: str | None

from enum import StrEnum

from pydantic import BaseModel

from camp_agent.domain.route_guard import Category, Route
from camp_agent.domain.urgency import Urgency


class Verdict(StrEnum):
    GENUINE = "genuine"
    SPAM = "spam"
    UNCLEAR = "unclear"


class VerifyOutput(BaseModel):
    verdict: Verdict


class SplitOutput(BaseModel):
    intents: list[str]


class Classification(BaseModel):
    category: Category
    route: Route
    urgency: Urgency

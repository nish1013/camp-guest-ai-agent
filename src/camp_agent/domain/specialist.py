from enum import StrEnum

from camp_agent.domain.route_guard import Category


class Team(StrEnum):
    MAINTENANCE = "maintenance"
    HOUSEKEEPING = "housekeeping"


_TEAMS = {Category.MAINTENANCE: Team.MAINTENANCE, Category.HOUSEKEEPING: Team.HOUSEKEEPING}


def specialist_for(category: Category) -> Team | None:
    return _TEAMS.get(category)

from sqlalchemy.ext.asyncio import AsyncEngine

from camp_agent.db.case_record import CaseRecord
from camp_agent.db.case_repository import CaseRepository


class FindCase:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    # A closed case is still shown: its last status is what the guest came back to read.
    async def __call__(self, case_token: str) -> CaseRecord | None:
        async with self._engine.connect() as conn:
            return await CaseRepository(conn).find_by_token(case_token)

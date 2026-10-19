from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from camp_agent.db.tables import status_notices


class StatusNoticeRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    # True only for the caller that moves the digest, so two writers never notify one change.
    async def claim(self, case_id: int, digest: str) -> bool:
        statement = insert(status_notices).values(case_id=case_id, digest=digest)
        claimed = await self._conn.execute(
            statement.on_conflict_do_update(
                index_elements=["case_id"],
                set_={"digest": statement.excluded.digest},
                where=status_notices.c.digest != statement.excluded.digest,
            ).returning(status_notices.c.case_id)
        )
        return claimed.one_or_none() is not None

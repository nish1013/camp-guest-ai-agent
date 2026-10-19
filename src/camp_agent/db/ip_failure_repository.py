from datetime import datetime

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from camp_agent.db.tables import ip_verification_failures


class IpFailureRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def insert(self, ip: str, now: datetime) -> None:
        await self._conn.execute(insert(ip_verification_failures).values(ip=ip, failed_at=now))

    async def count_since(self, ip: str, since: datetime) -> int:
        query = select(func.count()).where(
            ip_verification_failures.c.ip == ip, ip_verification_failures.c.failed_at > since
        )
        failures: int = (await self._conn.execute(query)).scalar_one()
        return failures

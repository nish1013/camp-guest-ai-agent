from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine


class DatabaseProbe:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def is_up(self) -> bool:
        try:
            async with self._engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except (SQLAlchemyError, OSError):
            return False
        return True

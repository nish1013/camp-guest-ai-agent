from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from camp_agent.config import Settings


def make_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": settings.db_connect_timeout_s},
    )

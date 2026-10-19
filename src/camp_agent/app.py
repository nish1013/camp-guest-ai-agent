from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from camp_agent.config import Settings
from camp_agent.db.engine import make_engine
from camp_agent.db.probe import DatabaseProbe
from camp_agent.http import health


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = make_engine(resolved)
        app.state.health_probe = DatabaseProbe(engine)
        yield
        await engine.dispose()

    app = FastAPI(title="Camp Guest AI Agent", lifespan=lifespan)
    app.include_router(health.router)
    return app

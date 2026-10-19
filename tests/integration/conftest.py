from collections.abc import AsyncIterator, Iterator

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from testcontainers.community.postgres import PostgresContainer

from camp_agent.app import create_app
from camp_agent.config import Settings
from tests.fakes import (
    FakeClock,
    FakeLlm,
    SwitchableGuide,
    SwitchableStays,
    demo_guide,
    demo_stays,
    oct_19,
)
from tests.integration.intake_support import SECRET, RecordingGraph


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine", driver="psycopg") as pg:
        yield pg.get_connection_url()


@pytest.fixture(scope="session")
def migrated_url(database_url: str) -> str:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    return database_url


@pytest.fixture
def db(migrated_url: str) -> Iterator[Engine]:
    engine = create_engine(migrated_url)
    with engine.begin() as conn:
        conn.execute(
            text("TRUNCATE messages, cases, ip_verification_failures RESTART IDENTITY CASCADE")
        )
    yield engine
    engine.dispose()


@pytest.fixture
async def async_db(db: Engine, migrated_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(migrated_url)
    yield engine
    await engine.dispose()


@pytest.fixture
def graph() -> RecordingGraph:
    return RecordingGraph()


@pytest.fixture
def guide() -> SwitchableGuide:
    return demo_guide()


@pytest.fixture
def stays() -> SwitchableStays:
    return demo_stays()


@pytest.fixture
def clock() -> FakeClock:
    return oct_19()


@pytest.fixture
def client(
    db: Engine,
    migrated_url: str,
    graph: RecordingGraph,
    clock: FakeClock,
    guide: SwitchableGuide,
    stays: SwitchableStays,
) -> Iterator[TestClient]:
    settings = Settings(database_url=migrated_url, secret_key=SECRET)
    app = create_app(settings, clock=clock, graph=graph, guide=guide, stays=stays)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def llm() -> FakeLlm:
    return FakeLlm()


@pytest.fixture
def triage_client(
    db: Engine,
    migrated_url: str,
    llm: FakeLlm,
    clock: FakeClock,
    guide: SwitchableGuide,
    stays: SwitchableStays,
) -> Iterator[TestClient]:
    settings = Settings(database_url=migrated_url, secret_key=SECRET, llm_retry_delay_s=0)
    app = create_app(settings, clock=clock, llm=llm, guide=guide, stays=stays)
    with TestClient(app) as test_client:
        yield test_client

from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from camp_agent.app import create_app
from camp_agent.config import Settings
from tests.fakes import (
    FakeClock,
    FakeLlm,
    RecordingNotifications,
    SwitchableGuide,
    SwitchableStays,
    demo_guide,
    demo_stays,
    oct_19,
)
from tests.integration.intake_support import SECRET, RecordingGraph


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
def notices() -> RecordingNotifications:
    return RecordingNotifications()


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
    notices: RecordingNotifications,
) -> Iterator[TestClient]:
    settings = Settings(
        database_url=migrated_url, secret_key=SECRET, outbox_poll_s=0, status_stream_s=0
    )
    app = create_app(
        settings, clock=clock, graph=graph, guide=guide, stays=stays, notifications=notices
    )
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
    notices: RecordingNotifications,
) -> Iterator[TestClient]:
    settings = Settings(
        database_url=migrated_url,
        secret_key=SECRET,
        llm_retry_delay_s=0,
        ticket_retry_delay_s=0,
        outbox_poll_s=0,
        status_stream_s=0,
    )
    app = create_app(
        settings, clock=clock, llm=llm, guide=guide, stays=stays, notifications=notices
    )
    with TestClient(app) as test_client:
        yield test_client

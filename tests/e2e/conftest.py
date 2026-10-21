import socket
import threading
import time
from collections.abc import Callable, Iterator

import pytest
import uvicorn
from playwright.sync_api import Browser
from sqlalchemy import Engine

from camp_agent.app import create_app
from camp_agent.config import Settings
from tests.e2e.pages import Camp
from tests.fakes import FakeLlm, RecordingNotifications, demo_guide, demo_stays, oct_19

SECRET = "e2e-secret"
STARTUP_S = 10.0

type Serve = Callable[[FakeLlm], Camp]


@pytest.fixture
def serve(db: Engine, migrated_url: str, browser: Browser) -> Iterator[Serve]:
    started: list[tuple[uvicorn.Server, threading.Thread, Camp]] = []

    def start(llm: FakeLlm) -> Camp:
        settings = Settings(
            database_url=migrated_url,
            secret_key=SECRET,
            llm_retry_delay_s=0,
            ticket_retry_delay_s=0,
            outbox_poll_s=0.2,
            status_poll_s=0.2,
        )
        app = create_app(
            settings,
            clock=oct_19(),
            llm=llm,
            guide=demo_guide(),
            stays=demo_stays(),
            notifications=RecordingNotifications(),
        )
        port = _free_port()
        server = uvicorn.Server(
            uvicorn.Config(
                app, host="127.0.0.1", port=port, log_level="warning", timeout_graceful_shutdown=1
            )
        )
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        _wait_started(server)
        camp = Camp(f"http://127.0.0.1:{port}", SECRET, browser, db)
        started.append((server, thread, camp))
        return camp

    yield start
    for server, thread, camp in started:
        camp.close()
        server.should_exit = True
        thread.join()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
    return port


def _wait_started(server: uvicorn.Server) -> None:
    deadline = time.monotonic() + STARTUP_S
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("the app did not start")
        time.sleep(0.05)

import socket

from fastapi.testclient import TestClient

from camp_agent.app import create_app
from camp_agent.config import Settings


def closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
    return port


def test_health_ok_against_postgres(database_url: str) -> None:
    with TestClient(create_app(Settings(database_url=database_url))) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["database"] == "ok"


def test_health_503_when_postgres_unreachable() -> None:
    url = f"postgresql+psycopg://camp:camp@127.0.0.1:{closed_port()}/camp"
    with TestClient(create_app(Settings(database_url=url))) as client:
        response = client.get("/health")

    assert response.status_code == 503
    assert response.json()["database"] == "unavailable"

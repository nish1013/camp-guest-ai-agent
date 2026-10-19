from fastapi.testclient import TestClient

from camp_agent.app import create_app
from camp_agent.http.health import HealthProbe, get_probe


class FakeProbe:
    def __init__(self, up: bool) -> None:
        self._up = up

    async def is_up(self) -> bool:
        return self._up


def client_with(probe: HealthProbe) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_probe] = lambda: probe
    return TestClient(app)


def test_health_ok_when_db_up() -> None:
    with client_with(FakeProbe(up=True)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_503_when_db_down() -> None:
    with client_with(FakeProbe(up=False)) as client:
        response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "unavailable"}

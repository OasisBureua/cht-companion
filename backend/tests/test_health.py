from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_ready() -> None:
    assert client.get("/health/ready").status_code == 200


def test_health_live() -> None:
    assert client.get("/health/live").status_code == 200

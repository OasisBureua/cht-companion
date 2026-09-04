from fastapi.testclient import TestClient


def test_health(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from main import app

    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


def test_health_ready_without_database_url(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from main import app

    with TestClient(app) as client:
        response = client.get("/health/ready")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "degraded"
        assert body["checks"]["database"] == "unavailable"


def test_health_live(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from main import app

    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200


def test_debug_kb_hello_requires_database(monkeypatch) -> None:
    monkeypatch.setenv("CHT_ENVIRONMENT", "development")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from main import app

    with TestClient(app) as client:
        response = client.post("/debug/kb-hello")
        assert response.status_code == 503

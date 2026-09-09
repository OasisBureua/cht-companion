from fastapi.testclient import TestClient


def test_chat_sse_named_events_and_shim(monkeypatch) -> None:
    monkeypatch.delenv("COMPANION_INTERNAL_SECRET", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from main import app

    with TestClient(app) as client:
        with client.stream("POST", "/chat", json={"query": "What is CHT?"}) as response:
            assert response.status_code == 200
            assert "text/event-stream" in response.headers["content-type"]
            assert response.headers.get("X-Api-Version") == "1.0.0"
            assert response.headers.get("X-Request-Id")
            body = "".join(response.iter_text())
    assert "event: citation" in body
    assert "event: token" in body
    assert "event: done" in body
    assert "data: [DONE]" in body
    assert "CHT?" in body


def test_chat_rejects_empty_query(monkeypatch) -> None:
    monkeypatch.delenv("COMPANION_INTERNAL_SECRET", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from main import app

    with TestClient(app) as client:
        response = client.post("/chat", json={"query": ""})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation"


def test_chat_requires_bff_auth_when_secret_set(monkeypatch) -> None:
    monkeypatch.setenv("COMPANION_INTERNAL_SECRET", "test-secret")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from api import config

    config.refresh_from_env()
    from main import app

    with TestClient(app) as client:
        denied = client.post("/chat", json={"query": "hello"})
        assert denied.status_code == 401
        ok = client.post(
            "/chat",
            json={"query": "hello"},
            headers={"X-BFF-Auth": "test-secret"},
        )
        assert ok.status_code == 200

    monkeypatch.delenv("COMPANION_INTERNAL_SECRET", raising=False)
    config.refresh_from_env()


def test_admin_sources_requires_admin_role(monkeypatch) -> None:
    monkeypatch.delenv("COMPANION_INTERNAL_SECRET", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from main import app

    with TestClient(app) as client:
        member = client.get("/admin/sources", headers={"X-User-Role": "member"})
        assert member.status_code == 403
        admin = client.get("/admin/sources", headers={"X-User-Role": "admin"})
        assert admin.status_code == 200
        assert admin.json()["items"] == []

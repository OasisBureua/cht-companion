from fastapi.testclient import TestClient

from api import admin_store


def test_cursor_roundtrip() -> None:
    encoded = admin_store._encode_cursor("2026-09-09T12:00:00+00:00", "yt:abc123")
    created_at, source_id = admin_store._decode_cursor(encoded)
    assert created_at == "2026-09-09T12:00:00+00:00"
    assert source_id == "yt:abc123"


def test_list_sources_requires_admin(monkeypatch) -> None:
    monkeypatch.delenv("COMPANION_INTERNAL_SECRET", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from main import app

    with TestClient(app) as client:
        member = client.get("/admin/sources", headers={"X-User-Role": "member"})
        assert member.status_code == 403
        admin = client.get("/admin/sources", headers={"X-User-Role": "admin"})
        assert admin.status_code == 200
        body = admin.json()
        assert body["items"] == []
        assert body["total"] == 0


def test_approve_requires_if_match(monkeypatch) -> None:
    monkeypatch.delenv("COMPANION_INTERNAL_SECRET", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from main import app

    with TestClient(app) as client:
        missing = client.post(
            "/admin/sources/yt:abc123/approve",
            json={},
            headers={"X-User-Role": "admin"},
        )
        assert missing.status_code == 428

        bad = client.post(
            "/admin/sources/yt:abc123/approve",
            json={},
            headers={"X-User-Role": "admin", "If-Match": "not-a-number"},
        )
        assert bad.status_code == 400


def test_approve_without_database_returns_503(monkeypatch) -> None:
    monkeypatch.delenv("COMPANION_INTERNAL_SECRET", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from main import app

    with TestClient(app) as client:
        response = client.post(
            "/admin/sources/yt:abc123/approve",
            json={},
            headers={"X-User-Role": "admin", "If-Match": "1"},
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "internal"


def test_get_source_without_database_returns_404(monkeypatch) -> None:
    monkeypatch.delenv("COMPANION_INTERNAL_SECRET", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from main import app

    with TestClient(app) as client:
        response = client.get(
            "/admin/sources/yt:abc123", headers={"X-User-Role": "admin"}
        )
        assert response.status_code == 404


def test_kb_stats_without_database_returns_zeros(monkeypatch) -> None:
    monkeypatch.delenv("COMPANION_INTERNAL_SECRET", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from main import app

    with TestClient(app) as client:
        response = client.get("/admin/kb/stats", headers={"X-User-Role": "admin"})
        assert response.status_code == 200
        body = response.json()
        assert body["pending"] == 0
        assert body["sources"] == 0


def test_reject_endpoint_exists_and_requires_if_match(monkeypatch) -> None:
    """Regression: reject_source() existed in admin_store with no route wired to it."""
    monkeypatch.delenv("COMPANION_INTERNAL_SECRET", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from main import app

    with TestClient(app) as client:
        missing_if_match = client.post(
            "/admin/sources/yt:abc123/reject",
            json={"reason": "not relevant"},
            headers={"X-User-Role": "admin"},
        )
        assert missing_if_match.status_code == 428

        no_db = client.post(
            "/admin/sources/yt:abc123/reject",
            json={"reason": "not relevant"},
            headers={"X-User-Role": "admin", "If-Match": "1"},
        )
        assert no_db.status_code == 503


def test_reindex_requires_if_match(monkeypatch) -> None:
    monkeypatch.delenv("COMPANION_INTERNAL_SECRET", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from main import app

    with TestClient(app) as client:
        response = client.post(
            "/admin/sources/yt:abc123/reindex", headers={"X-User-Role": "admin"}
        )
        assert response.status_code == 428


def test_reindex_without_database_returns_503(monkeypatch) -> None:
    """Regression: reindex_source() previously returned a fake random UUID
    with no database write when DB was unconfigured — now it correctly
    reports 503 like every other admin mutation route.
    """
    monkeypatch.delenv("COMPANION_INTERNAL_SECRET", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from main import app

    with TestClient(app) as client:
        response = client.post(
            "/admin/sources/yt:abc123/reindex",
            headers={"X-User-Role": "admin", "If-Match": "1"},
        )
        assert response.status_code == 503


def test_whitespace_database_url_does_not_crash_app(monkeypatch) -> None:
    """Regression: a whitespace-only DATABASE_URL passed the truthy os.environ.get
    check in 3 places but failed db.database_url()'s .strip() deeper in the call
    stack, crashing app startup entirely. database_configured() fixes this.
    """
    monkeypatch.setenv("DATABASE_URL", "   ")
    monkeypatch.delenv("COMPANION_INTERNAL_SECRET", raising=False)
    from main import app

    with TestClient(app) as client:
        with client.stream("POST", "/chat", json={"query": "hi"}) as response:
            assert response.status_code == 200
        admin_response = client.get(
            "/admin/sources", headers={"X-User-Role": "admin"}
        )
        assert admin_response.status_code == 200

    monkeypatch.delenv("DATABASE_URL", raising=False)

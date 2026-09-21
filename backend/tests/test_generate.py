from unittest.mock import patch

from fastapi.testclient import TestClient


def test_generate_returns_completion(monkeypatch) -> None:
    monkeypatch.delenv("COMPANION_INTERNAL_SECRET", raising=False)
    from main import app

    with patch("api.routers.generate.generate_completion") as mock_generate:
        mock_generate.return_value = ("Generated report text.", "complete")

        with TestClient(app) as client:
            response = client.post(
                "/generate",
                json={"system_prompt": "You generate reports.", "user_content": "Transcript here."},
            )

    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "Generated report text."
    assert body["finish_reason"] == "complete"
    assert body["request_id"]


def test_generate_rejects_empty_system_prompt(monkeypatch) -> None:
    monkeypatch.delenv("COMPANION_INTERNAL_SECRET", raising=False)
    from main import app

    with TestClient(app) as client:
        response = client.post(
            "/generate", json={"system_prompt": "", "user_content": "Transcript here."}
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation"


def test_generate_requires_bff_auth_when_secret_set(monkeypatch) -> None:
    monkeypatch.setenv("COMPANION_INTERNAL_SECRET", "test-secret")
    from api import config

    config.refresh_from_env()
    try:
        from main import app

        with TestClient(app) as client:
            response = client.post(
                "/generate",
                json={"system_prompt": "You generate reports.", "user_content": "Transcript here."},
            )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthorized"
    finally:
        monkeypatch.delenv("COMPANION_INTERNAL_SECRET", raising=False)
        config.refresh_from_env()


def test_generate_accepts_valid_bff_auth_header(monkeypatch) -> None:
    monkeypatch.setenv("COMPANION_INTERNAL_SECRET", "test-secret")
    from api import config

    config.refresh_from_env()
    try:
        from main import app

        with patch("api.routers.generate.generate_completion") as mock_generate:
            mock_generate.return_value = ("Text.", "complete")
            with TestClient(app) as client:
                response = client.post(
                    "/generate",
                    json={"system_prompt": "You generate reports.", "user_content": "Transcript here."},
                    headers={"X-BFF-Auth": "test-secret"},
                )
        assert response.status_code == 200
    finally:
        monkeypatch.delenv("COMPANION_INTERNAL_SECRET", raising=False)
        config.refresh_from_env()


def test_generate_maps_generation_error_to_502(monkeypatch) -> None:
    monkeypatch.delenv("COMPANION_INTERNAL_SECRET", raising=False)
    from api.bedrock import GenerationError
    from main import app

    with patch("api.routers.generate.generate_completion") as mock_generate:
        mock_generate.side_effect = GenerationError("bedrock unavailable")

        with TestClient(app) as client:
            response = client.post(
                "/generate",
                json={"system_prompt": "You generate reports.", "user_content": "Transcript here."},
            )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "llm_timeout"

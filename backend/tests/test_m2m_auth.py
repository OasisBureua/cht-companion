import time
from unittest.mock import patch

import jwt
import pytest
from fastapi.testclient import TestClient

from api import config, m2m

TEST_KEY = "test-signing-key-at-least-32-bytes-long"
BODY = {"system_prompt": "You generate reports.", "user_content": "Transcript here."}


def _token(scope: str, *, key: str = TEST_KEY, exp_in: int = 300, token_use: str = "access") -> str:
    claims = {"client_id": "reports-client", "scope": scope, "token_use": token_use, "exp": int(time.time()) + exp_in}
    return jwt.encode(claims, key, algorithm="HS256")


@pytest.fixture
def client(monkeypatch):
    def configure(mode: str, *, secret: str = "bff-secret") -> TestClient:
        monkeypatch.setenv("COMPANION_AUTH_MODE", mode)
        monkeypatch.setenv("COMPANION_INTERNAL_SECRET", secret)
        monkeypatch.setenv("COMPANION_M2M_TEST_SECRET", TEST_KEY)
        monkeypatch.delenv("COMPANION_M2M_ISSUER", raising=False)
        config.refresh_from_env()
        from main import app

        return TestClient(app)

    yield configure
    monkeypatch.delenv("COMPANION_AUTH_MODE", raising=False)
    monkeypatch.delenv("COMPANION_INTERNAL_SECRET", raising=False)
    monkeypatch.delenv("COMPANION_M2M_TEST_SECRET", raising=False)
    config.refresh_from_env()


def _post(client: TestClient, headers: dict) -> int:
    with patch("api.routers.generate.generate_completion") as mock_generate:
        mock_generate.return_value = ("Report.", "complete", {"input_tokens": 1, "output_tokens": 1})
        with client:
            return client.post("/generate", json=BODY, headers=headers).status_code


def test_m2m_mode_accepts_token_with_scope(client) -> None:
    headers = {"Authorization": f"Bearer {_token('companion/generate.invoke')}"}
    assert _post(client("m2m"), headers) == 200


def test_m2m_mode_rejects_shared_secret(client) -> None:
    assert _post(client("m2m"), {"X-BFF-Auth": "bff-secret"}) == 401


def test_m2m_mode_rejects_token_without_scope(client) -> None:
    headers = {"Authorization": f"Bearer {_token('companion/chat.invoke')}"}
    assert _post(client("m2m"), headers) == 403


def test_m2m_mode_rejects_bad_signature_expired_and_id_tokens(client) -> None:
    app_client = client("m2m")
    for token in (
        _token("companion/generate.invoke", key="another-key-that-is-at-least-32-bytes"),
        _token("companion/generate.invoke", exp_in=-60),
        _token("companion/generate.invoke", token_use="id"),
    ):
        assert _post(app_client, {"Authorization": f"Bearer {token}"}) == 401


def test_either_mode_accepts_token_or_secret(client) -> None:
    app_client = client("either")
    assert _post(app_client, {"Authorization": f"Bearer {_token('companion/generate.invoke')}"}) == 200
    assert _post(app_client, {"X-BFF-Auth": "bff-secret"}) == 200
    assert _post(app_client, {}) == 401


def test_either_mode_does_not_fall_back_when_token_is_invalid(client) -> None:
    headers = {"Authorization": "Bearer not-a-jwt", "X-BFF-Auth": "bff-secret"}
    assert _post(client("either"), headers) == 401


def test_secret_mode_ignores_bearer_tokens(client) -> None:
    app_client = client("secret")
    assert _post(app_client, {"Authorization": f"Bearer {_token('companion/generate.invoke')}"}) == 401
    assert _post(app_client, {"X-BFF-Auth": "bff-secret"}) == 200


def test_unknown_mode_fails_closed_to_m2m(client) -> None:
    assert _post(client("bogus"), {"X-BFF-Auth": "bff-secret"}) == 401


def test_issuer_aliases_cover_both_cognito_hosts() -> None:
    aliases = m2m.issuer_aliases("https://cognito-idp.us-east-1.amazonaws.com/us-east-1_abc/")
    assert aliases == [
        "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_abc",
        "https://issuer-cognito-idp.us-east-1.amazonaws.com/us-east-1_abc",
    ]

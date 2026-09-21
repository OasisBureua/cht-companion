import json
from unittest.mock import MagicMock, patch

import pytest

from youtube_auth import YouTubeAuthError, _oauth_payload, get_credentials


def test_oauth_payload_raises_when_env_not_set(monkeypatch) -> None:
    monkeypatch.delenv("YOUTUBE_OAUTH_SECRET_ARN", raising=False)
    _oauth_payload.cache_clear()
    with pytest.raises(YouTubeAuthError, match="YOUTUBE_OAUTH_SECRET_ARN is not set"):
        _oauth_payload()
    _oauth_payload.cache_clear()


def test_oauth_payload_raises_on_missing_fields(monkeypatch) -> None:
    monkeypatch.setenv("YOUTUBE_OAUTH_SECRET_ARN", "arn:test")
    _oauth_payload.cache_clear()
    mock_client = MagicMock()
    mock_client.get_secret_value.return_value = {"SecretString": json.dumps({"client_id": "x"})}
    with patch("youtube_auth._secretsmanager_client", return_value=mock_client):
        with pytest.raises(YouTubeAuthError, match="missing fields"):
            _oauth_payload()
    _oauth_payload.cache_clear()


def test_get_credentials_builds_from_secret(monkeypatch) -> None:
    monkeypatch.setenv("YOUTUBE_OAUTH_SECRET_ARN", "arn:test")
    _oauth_payload.cache_clear()
    mock_client = MagicMock()
    mock_client.get_secret_value.return_value = {
        "SecretString": json.dumps(
            {"client_id": "cid", "client_secret": "csecret", "refresh_token": "rtoken"}
        )
    }
    with patch("youtube_auth._secretsmanager_client", return_value=mock_client):
        creds = get_credentials()
    assert creds.client_id == "cid"
    assert creds.client_secret == "csecret"
    assert creds.refresh_token == "rtoken"
    assert "youtube.force-ssl" in creds.scopes[0]
    _oauth_payload.cache_clear()

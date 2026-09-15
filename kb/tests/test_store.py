import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from store import ChunkInput, SourceInput, content_hash, database_url, _database_url_from_secret, _vector_literal


def test_content_hash_stable_for_same_text() -> None:
    assert content_hash("hello world") == content_hash("hello world")


def test_content_hash_differs_for_different_text() -> None:
    assert content_hash("hello world") != content_hash("goodbye world")


def test_vector_literal_shape() -> None:
    lit = _vector_literal([0.1, 0.2, 0.3] + [0.0] * 1021)
    assert lit.startswith("[") and lit.endswith("]")
    assert lit.count(",") == 1023


def test_vector_literal_rejects_wrong_dim() -> None:
    try:
        _vector_literal([0.1, 0.2])
    except ValueError as exc:
        assert "1024" in str(exc)
    else:
        raise AssertionError("expected ValueError for wrong embedding dim")


def test_source_input_defaults() -> None:
    s = SourceInput(
        source_id="youtube_caption:abc123",
        source_type="youtube_caption",
        title="Test Video",
        url="https://youtube.com/watch?v=abc123",
        embedding_model="amazon.titan-embed-text-v2:0",
    )
    assert s.doctors == []
    assert s.topics == []
    assert s.content_date is None


def test_chunk_input_defaults() -> None:
    c = ChunkInput(index=0, text="hello", embedding=[0.0] * 1024)
    assert c.speakers_in_chunk == []
    assert c.timestamp_start is None


def test_database_url_prefers_plain_env_var(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://local/db")
    monkeypatch.delenv("DATABASE_SECRET_ARN", raising=False)
    assert database_url() == "postgresql://local/db"


def test_database_url_raises_when_neither_set(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_SECRET_ARN", raising=False)
    with pytest.raises(RuntimeError, match="neither DATABASE_URL nor DATABASE_SECRET_ARN"):
        database_url()


def test_database_url_falls_back_to_secret_arn(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_SECRET_ARN", "arn:aws:secretsmanager:us-east-1:123:secret:test-XXXXXX")
    _database_url_from_secret.cache_clear()

    mock_client = MagicMock()
    mock_client.get_secret_value.return_value = {
        "SecretString": json.dumps({"url": "postgresql://secret-resolved/db"})
    }
    with patch("store._secretsmanager_client", return_value=mock_client):
        assert database_url() == "postgresql://secret-resolved/db"
    mock_client.get_secret_value.assert_called_once_with(
        SecretId="arn:aws:secretsmanager:us-east-1:123:secret:test-XXXXXX"
    )
    _database_url_from_secret.cache_clear()


def test_database_url_from_secret_raises_on_missing_url_key(monkeypatch) -> None:
    _database_url_from_secret.cache_clear()
    mock_client = MagicMock()
    mock_client.get_secret_value.return_value = {"SecretString": json.dumps({"username": "x"})}
    with patch("store._secretsmanager_client", return_value=mock_client):
        with pytest.raises(RuntimeError, match="no 'url' field"):
            _database_url_from_secret("arn:test")
    _database_url_from_secret.cache_clear()

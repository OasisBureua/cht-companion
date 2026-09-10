import asyncio

from fastapi.testclient import TestClient


def _drain(async_gen):
    """Collect an async generator's yields synchronously (no async test plugin in this suite)."""

    async def _collect():
        return [item async for item in async_gen]

    return asyncio.run(_collect())


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


def test_retrieval_chat_stream_emits_llm_timeout_on_generation_failure(monkeypatch) -> None:
    """Generation failure (Bedrock unreachable/throttled) is terminal: an
    llm_timeout ErrorEvent is emitted and the stream still closes with a
    'done' event (finish_reason=error) rather than hanging or raising.
    """
    from api import bedrock, sse

    monkeypatch.setattr(sse, "embed_query", lambda _query: [])
    monkeypatch.setattr(sse, "retrieve", lambda _embedding: [])

    def _raise_generation_error(*_args, **_kwargs):
        raise bedrock.GenerationError("boto3 network unreachable")
        yield  # pragma: no cover — makes this a generator function

    monkeypatch.setattr(sse, "stream_generation", _raise_generation_error)

    lines = _drain(sse.retrieval_chat_stream("test query", "req-1"))
    body = "".join(lines)

    assert "event: error" in body
    assert '"code":"llm_timeout"' in body
    assert "event: done" in body
    assert '"finish_reason":"error"' in body


def test_retrieval_chat_stream_streams_generation_deltas(monkeypatch) -> None:
    from api import sse

    monkeypatch.setattr(sse, "embed_query", lambda _query: [])
    monkeypatch.setattr(sse, "retrieve", lambda _embedding: [])

    def _fake_stream(_query, _context_block, **_kwargs):
        yield "Hello"
        yield " world"

    monkeypatch.setattr(sse, "stream_generation", _fake_stream)

    lines = _drain(sse.retrieval_chat_stream("test query", "req-1"))
    body = "".join(lines)

    assert "event: token" in body
    assert '"text":"Hello"' in body
    assert '"text":" world"' in body
    assert "event: done" in body
    assert '"finish_reason":"complete"' in body
    assert '"tokens_generated":2' in body


def test_retrieval_chat_stream_maps_max_tokens_stop_reason_to_truncated(monkeypatch) -> None:
    """Regression: stream_generation previously discarded Bedrock's
    messageStop.stopReason entirely, so a response cut off by max_tokens
    was indistinguishable from a normal completion in the done event.
    """
    from api import sse

    monkeypatch.setattr(sse, "embed_query", lambda _query: [])
    monkeypatch.setattr(sse, "retrieve", lambda _embedding: [])

    def _fake_stream_truncated(_query, _context_block, **_kwargs):
        yield "Partial answer"
        return "truncated"

    monkeypatch.setattr(sse, "stream_generation", _fake_stream_truncated)

    lines = _drain(sse.retrieval_chat_stream("test query", "req-1"))
    body = "".join(lines)

    assert '"finish_reason":"truncated"' in body


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

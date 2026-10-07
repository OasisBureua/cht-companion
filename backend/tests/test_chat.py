import asyncio

from fastapi.testclient import TestClient


def _drain(async_gen):
    """Collect an async generator's yields synchronously (no async test plugin in this suite)."""

    async def _collect():
        return [item async for item in async_gen]

    return asyncio.run(_collect())


def _no_sources(query, _history, **_kwargs):
    from api.rag import RagResult

    return RagResult(
        sources=[], search_query=query, candidates=0, reranked=False, top_distance=None, top_rerank_score=None
    )


def _rag_with(sources, query="q"):
    from api.rag import RagResult

    return RagResult(
        sources=sources, search_query=query, candidates=len(sources), reranked=True, top_distance=0.2, top_rerank_score=0.9
    )


def _source(source_id: str, *chunk_indexes: int):
    from api.retrieval import RetrievedChunk, SourceContext

    hits = [
        RetrievedChunk(
            chunk_id=f"{source_id}:{i}",
            source_id=source_id,
            source_type="curated_doc",
            chunk_index=i,
            title=f"Title {source_id}",
            url=f"https://example.com/{source_id}",
            playlist_url=None,
            text=f"text {i}",
            timestamp_start=None,
        )
        for i in chunk_indexes
    ]
    return SourceContext(
        source_id=source_id,
        source_type="curated_doc",
        title=f"Title {source_id}",
        url=f"https://example.com/{source_id}",
        playlist_url=None,
        best=hits[0],
        hits=hits,
        context_text=" ".join(h.text for h in hits),
    )


def test_retrieval_chat_stream_emits_one_citation_per_source(monkeypatch) -> None:
    from api import sse

    monkeypatch.setattr(
        sse, "find_sources", lambda query, _history, **_kw: _rag_with([_source("s1", 3, 7), _source("s2", 0)], query)
    )
    seen = {}

    def _fake_stream(_query, context_block, **kwargs):
        seen["context"] = context_block
        seen["history"] = kwargs.get("history")
        yield "ok"

    monkeypatch.setattr(sse, "stream_generation", _fake_stream)

    body = "".join(_drain(sse.retrieval_chat_stream("q", "req-1", history=[{"role": "user", "content": "hi"}])))

    assert body.count("event: citation") == 2
    assert '"citation_id":"c1","source_id":"s1","chunk_id":"s1:3"' in body
    assert '"citations_emitted":2' in body
    assert seen["context"].startswith("[c1] (Title s1):\ntext 3 text 7")
    assert "[c2] (Title s2):" in seen["context"]
    assert seen["history"] == [{"role": "user", "content": "hi"}]


def test_retrieval_chat_stream_degrades_when_retrieval_raises(monkeypatch) -> None:
    from api import sse

    def _boom(*_args, **_kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(sse, "find_sources", _boom)
    monkeypatch.setattr(sse, "stream_generation", lambda *_a, **_k: iter(["answer"]))

    body = "".join(_drain(sse.retrieval_chat_stream("q", "req-1")))

    assert '"code":"retrieval_degraded"' in body
    assert "event: citation" not in body
    assert '"text":"answer"' in body


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

    monkeypatch.setattr(sse, "find_sources", _no_sources)

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

    monkeypatch.setattr(sse, "find_sources", _no_sources)

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

    monkeypatch.setattr(sse, "find_sources", _no_sources)

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

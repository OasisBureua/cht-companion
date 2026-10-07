from api import rag
from api.bedrock import RerankError, RewriteError
from api.retrieval import RetrievedChunk


def _candidate(chunk_id: str, distance: float | None = 0.3) -> RetrievedChunk:
    source_id = chunk_id.split(":")[0]
    return RetrievedChunk(
        chunk_id=chunk_id,
        source_id=source_id,
        source_type="curated_doc",
        chunk_index=int(chunk_id.split(":")[1]),
        title=source_id,
        url="https://example.com",
        playlist_url=None,
        text=f"text {chunk_id}",
        timestamp_start=None,
        distance=distance,
    )


def _wire(monkeypatch, candidates, *, rerank_result=None, rerank_error=None, rewrite=None):
    calls = {}

    def _rewrite(query, history, **_kw):
        calls["rewrite"] = (query, history)
        if isinstance(rewrite, Exception):
            raise rewrite
        return rewrite

    def _search(_embedding, query_text):
        calls["search"] = query_text
        return candidates

    def _rerank(query, documents, **_kw):
        calls["rerank"] = (query, documents)
        if rerank_error:
            raise rerank_error
        return rerank_result

    monkeypatch.setattr(rag, "rewrite_query", _rewrite)
    monkeypatch.setattr(rag, "embed_query", lambda text: [0.0])
    monkeypatch.setattr(rag, "search", _search)
    monkeypatch.setattr(rag, "rerank", _rerank)
    monkeypatch.setattr(rag, "build_sources", lambda hits: hits)
    return calls


def test_no_history_searches_the_question_as_asked(monkeypatch) -> None:
    calls = _wire(monkeypatch, [_candidate("a:0")], rerank_result=[(0, 0.9)])

    result = rag.find_sources("What is CHT?", [], request_id="r")

    assert "rewrite" not in calls
    assert calls["search"] == "What is CHT?"
    assert result.search_query == "What is CHT?"


def test_follow_up_is_rewritten_before_search(monkeypatch) -> None:
    history = [{"role": "user", "content": "Tell me about DB-12"}, {"role": "assistant", "content": "It is a trial."}]
    calls = _wire(
        monkeypatch, [_candidate("a:0")], rerank_result=[(0, 0.9)], rewrite="DB-12 results in brain metastases"
    )

    result = rag.find_sources("what about brain mets?", history, request_id="r")

    assert calls["search"] == "DB-12 results in brain metastases"
    assert calls["rerank"][0] == "DB-12 results in brain metastases"
    assert result.search_query == "DB-12 results in brain metastases"


def test_failed_rewrite_falls_back_to_raw_question(monkeypatch) -> None:
    calls = _wire(monkeypatch, [], rewrite=RewriteError("throttled"))

    rag.find_sources("what about brain mets?", [{"role": "user", "content": "x"}], request_id="r")

    assert calls["search"] == "what about brain mets?"


def test_rerank_reorders_and_drops_low_scores(monkeypatch) -> None:
    candidates = [_candidate("a:0"), _candidate("b:0"), _candidate("c:0")]
    _wire(monkeypatch, candidates, rerank_result=[(2, 0.8), (0, 0.4), (1, 0.01)])

    result = rag.find_sources("q", [], request_id="r")

    assert [c.chunk_id for c in result.sources] == ["c:0", "a:0"]
    assert result.reranked is True
    assert result.top_rerank_score == 0.8


def test_everything_below_threshold_means_no_context(monkeypatch) -> None:
    _wire(monkeypatch, [_candidate("a:0")], rerank_result=[(0, 0.02)])

    result = rag.find_sources("What is CHT?", [], request_id="r")

    assert result.sources == []


def test_rerank_failure_keeps_fused_order(monkeypatch) -> None:
    candidates = [_candidate(f"s{i}:0") for i in range(12)]
    _wire(monkeypatch, candidates, rerank_error=RerankError("no access"))

    result = rag.find_sources("q", [], request_id="r")

    assert [c.chunk_id for c in result.sources] == [f"s{i}:0" for i in range(rag.RERANK_TOP_N)]
    assert result.reranked is False


def test_reports_closest_vector_distance(monkeypatch) -> None:
    _wire(monkeypatch, [_candidate("a:0", 0.5), _candidate("b:0", 0.25), _candidate("c:0", None)], rerank_result=[])

    result = rag.find_sources("q", [], request_id="r")

    assert result.top_distance == 0.25
    assert result.candidates == 3

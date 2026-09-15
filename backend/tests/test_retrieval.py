from unittest.mock import MagicMock

from api.retrieval import RetrievedChunk, _fetch_siblings, retrieve


def _row(source_id: str, chunk_index: int, text: str, **overrides) -> dict:
    base = {
        "chunk_id": f"{source_id}:{chunk_index}",
        "source_id": source_id,
        "source_type": "youtube_caption",
        "chunk_index": chunk_index,
        "title": "Test Source",
        "url": "https://youtube.com/watch?v=abc",
        "playlist_url": None,
        "text": text,
        "timestamp_start": None,
    }
    base.update(overrides)
    return base


def test_fetch_siblings_includes_neighbors_in_order() -> None:
    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = [
        {"source_id": "s1", "chunk_index": 4, "text": "before"},
        {"source_id": "s1", "chunk_index": 5, "text": "matched"},
        {"source_id": "s1", "chunk_index": 6, "text": "after"},
    ]
    hits = [_row("s1", 5, "matched")]

    context = _fetch_siblings(conn, hits)

    assert context[("s1", 5)] == "before matched after"


def test_fetch_siblings_falls_back_to_own_text_when_no_neighbors_approved() -> None:
    conn = MagicMock()
    # Only the matched chunk itself comes back (neighbors not approved / don't exist)
    conn.execute.return_value.fetchall.return_value = [
        {"source_id": "s1", "chunk_index": 5, "text": "matched only"},
    ]
    hits = [_row("s1", 5, "matched only")]

    context = _fetch_siblings(conn, hits)

    assert context[("s1", 5)] == "matched only"


def test_fetch_siblings_empty_hits_returns_empty_dict() -> None:
    conn = MagicMock()
    assert _fetch_siblings(conn, []) == {}
    conn.execute.assert_not_called()


def test_fetch_siblings_does_not_cross_source_boundary() -> None:
    conn = MagicMock()
    # Two different sources both have a chunk_index=5 hit; siblings must not mix.
    conn.execute.return_value.fetchall.return_value = [
        {"source_id": "s1", "chunk_index": 4, "text": "s1-before"},
        {"source_id": "s1", "chunk_index": 5, "text": "s1-matched"},
        {"source_id": "s2", "chunk_index": 5, "text": "s2-matched"},
        {"source_id": "s2", "chunk_index": 6, "text": "s2-after"},
    ]
    hits = [_row("s1", 5, "s1-matched"), _row("s2", 5, "s2-matched")]

    context = _fetch_siblings(conn, hits)

    assert context[("s1", 5)] == "s1-before s1-matched"
    assert context[("s2", 5)] == "s2-matched s2-after"


def test_retrieve_returns_context_text_extended_with_siblings(monkeypatch) -> None:
    fake_conn = MagicMock()
    top_k_result = MagicMock()
    top_k_result.fetchall.return_value = [_row("s1", 5, "matched")]
    siblings_result = MagicMock()
    siblings_result.fetchall.return_value = [
        {"source_id": "s1", "chunk_index": 4, "text": "before"},
        {"source_id": "s1", "chunk_index": 5, "text": "matched"},
        {"source_id": "s1", "chunk_index": 6, "text": "after"},
    ]
    # First execute() call is SET LOCAL, second is the top-k query, third is siblings.
    fake_conn.execute.side_effect = [MagicMock(), top_k_result, siblings_result]

    conn_cm = MagicMock()
    conn_cm.__enter__.return_value = fake_conn
    monkeypatch.setattr("api.retrieval.connect", lambda: conn_cm)

    results = retrieve([0.0] * 1024, k=1)

    assert len(results) == 1
    chunk = results[0]
    assert isinstance(chunk, RetrievedChunk)
    assert chunk.text == "matched"  # citation text stays the matched chunk only
    assert chunk.context_text == "before matched after"  # generation context is extended

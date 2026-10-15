from unittest.mock import MagicMock

from api.retrieval import (
    RetrievedChunk,
    _fetch_neighbors,
    fuse,
    group_by_source,
    keyword_query,
    retrieve,
)


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


def _chunk(source_id: str, chunk_index: int, text: str = "t") -> RetrievedChunk:
    return fuse([_row(source_id, chunk_index, text)], [], max_distance=None)[0]


def test_keyword_query_ors_terms_and_keeps_trial_names() -> None:
    assert (
        keyword_query("What did DB-12 show for brain mets?")
        == "What or did or DB-12 or DB12 or show or for or brain or mets"
    )


def test_keyword_query_adds_hyphenated_spelling_of_trial_codes() -> None:
    assert keyword_query("DB12 results") == "DB12 or DB-12 or results"


def test_keyword_query_drops_operators_negation_and_duplicates() -> None:
    assert keyword_query("-HER2 or HER2 and not low") == "HER2 or HER-2 or low"
    assert keyword_query("?!") is None


def test_fuse_keeps_keyword_hit_that_vector_search_missed() -> None:
    vector = [_row("s1", 0, "vector only", distance=0.3)]
    keyword = [_row("s2", 4, "DB-12 exact match")]

    fused = fuse(vector, keyword)

    assert {c.chunk_id for c in fused} == {"s1:0", "s2:4"}


def test_fuse_ranks_chunk_found_by_both_searches_first() -> None:
    vector = [_row("s1", 0, "a", distance=0.2), _row("s2", 0, "b", distance=0.3)]
    keyword = [_row("s2", 0, "b")]

    fused = fuse(vector, keyword)

    assert fused[0].chunk_id == "s2:0"
    assert fused[0].distance == 0.3


def test_fuse_drops_far_vector_hits_unless_keyword_also_matched() -> None:
    vector = [_row("s1", 0, "far", distance=0.95), _row("s2", 0, "far but named", distance=0.95)]
    keyword = [_row("s2", 0, "far but named")]

    fused = fuse(vector, keyword, max_distance=0.8)

    assert [c.chunk_id for c in fused] == ["s2:0"]


def test_fetch_neighbors_groups_text_by_source_and_index() -> None:
    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = [
        {"source_id": "s1", "chunk_index": 4, "text": "before"},
        {"source_id": "s1", "chunk_index": 5, "text": "matched"},
        {"source_id": "s2", "chunk_index": 1, "text": "other"},
    ]

    neighbors = _fetch_neighbors(conn, [_chunk("s1", 5), _chunk("s2", 1)])

    assert neighbors == {"s1": {4: "before", 5: "matched"}, "s2": {1: "other"}}


def test_fetch_neighbors_empty_hits_skips_query() -> None:
    conn = MagicMock()
    assert _fetch_neighbors(conn, []) == {}
    conn.execute.assert_not_called()


def test_group_by_source_gives_one_entry_per_source_in_best_hit_order() -> None:
    hits = [_chunk("s1", 5, "a"), _chunk("s2", 0, "b"), _chunk("s1", 9, "c")]

    sources = group_by_source(hits, {})

    assert [s.source_id for s in sources] == ["s1", "s2"]
    assert sources[0].best.chunk_index == 5
    assert [h.chunk_index for h in sources[0].hits] == [5, 9]


def test_group_by_source_merges_overlapping_windows_without_repeating_text() -> None:
    hits = [_chunk("s1", 5, "five"), _chunk("s1", 6, "six")]
    neighbors = {"s1": {4: "four", 5: "five", 6: "six", 7: "seven"}}

    [source] = group_by_source(hits, neighbors)

    assert source.context_text == "four five six seven"


def test_group_by_source_separates_non_adjacent_passages() -> None:
    hits = [_chunk("s1", 2, "two"), _chunk("s1", 10, "ten")]
    neighbors = {"s1": {2: "two", 3: "three", 10: "ten"}}

    [source] = group_by_source(hits, neighbors)

    assert source.context_text == "two three\n\n…\n\nten"


def test_retrieve_runs_vector_keyword_and_neighbor_queries(monkeypatch) -> None:
    search_conn = MagicMock()
    vector_result = MagicMock()
    vector_result.fetchall.return_value = [_row("s1", 5, "matched", distance=0.2)]
    keyword_result = MagicMock()
    keyword_result.fetchall.return_value = []
    search_conn.execute.side_effect = [MagicMock(), vector_result, keyword_result]

    neighbor_conn = MagicMock()
    neighbor_conn.execute.return_value.fetchall.return_value = [
        {"source_id": "s1", "chunk_index": 4, "text": "before"},
        {"source_id": "s1", "chunk_index": 5, "text": "matched"},
        {"source_id": "s1", "chunk_index": 6, "text": "after"},
    ]

    conns = iter([search_conn, neighbor_conn])

    def _connect():
        cm = MagicMock()
        cm.__enter__.return_value = next(conns)
        return cm

    monkeypatch.setattr("api.retrieval.connect", _connect)

    [source] = retrieve([0.0] * 1024, "what did the trial show", k=1)

    assert source.best.text == "matched"
    assert source.context_text == "before matched after"
    keyword_sql, keyword_params = search_conn.execute.call_args_list[2].args
    assert "websearch_to_tsquery" in keyword_sql
    assert keyword_params[0] == "what or did or the or trial or show"

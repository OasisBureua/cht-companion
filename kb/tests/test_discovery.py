from unittest.mock import MagicMock, patch

import httpx

from discovery import (
    CandidateSource,
    _source_id_for_clip,
    fetch_catalog_page,
    find_new_sources,
    known_source_ids,
)


def test_source_id_for_clip_extracts_youtube_id() -> None:
    assert _source_id_for_clip("official:youtube:abc123") == "youtube_caption:abc123"


def test_source_id_matches_bootstrap_loader_scheme() -> None:
    # ingest.py's make_source_id("youtube_caption", "abc123") must produce the
    # same id, so catalog-discovered and bootstrap-loaded rows for the same
    # video collide on source_id rather than duplicating.
    from ingest import make_source_id

    assert _source_id_for_clip("official:youtube:abc123") == make_source_id("youtube_caption", "abc123")


def test_known_source_ids_reads_from_sources_table() -> None:
    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = [
        {"source_id": "youtube_caption:a"},
        {"source_id": "youtube_caption:b"},
    ]
    result = known_source_ids(conn)
    assert result == {"youtube_caption:a", "youtube_caption:b"}


def test_fetch_catalog_page_calls_expected_endpoint() -> None:
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.json.return_value = {"items": [{"id": "official:youtube:x", "title": "T"}]}
    mock_client.get.return_value = mock_response

    items = fetch_catalog_page(limit=10, offset=0, client=mock_client)

    assert items == [{"id": "official:youtube:x", "title": "T"}]
    mock_client.get.assert_called_once()
    call_kwargs = mock_client.get.call_args
    assert call_kwargs.kwargs["params"] == {"limit": 10, "offset": 0, "sort_by": "recent"}


def test_fetch_catalog_page_raises_on_http_error() -> None:
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "500", request=MagicMock(), response=MagicMock()
    )
    mock_client.get.return_value = mock_response

    try:
        fetch_catalog_page(client=mock_client)
    except httpx.HTTPStatusError:
        pass
    else:
        raise AssertionError("expected HTTPStatusError to propagate")


@patch("discovery.connect")
@patch("discovery.fetch_catalog_page")
def test_find_new_sources_filters_known_ids(mock_fetch, mock_connect) -> None:
    conn_cm = MagicMock()
    fake_conn = MagicMock()
    fake_conn.execute.return_value.fetchall.return_value = [{"source_id": "youtube_caption:already_known"}]
    conn_cm.__enter__.return_value = fake_conn
    mock_connect.return_value = conn_cm

    mock_fetch.side_effect = [
        [
            {
                "id": "official:youtube:already_known",
                "title": "Old",
                "youtube_url": "https://youtube.com/watch?v=already_known",
                "doctors": [],
                "tags": [],
                "posted_at": "2026-01-01T00:00:00Z",
            },
            {
                "id": "official:youtube:new_one",
                "title": "New",
                "youtube_url": "https://youtube.com/watch?v=new_one",
                "doctors": ["Dr. Test"],
                "tags": ["topic:HER2"],
                "posted_at": "2026-09-01T00:00:00Z",
            },
        ],
        [],  # next page empty -> loop stops
    ]

    result = find_new_sources(max_pages=5)

    assert len(result) == 1
    assert result[0].source_id == "youtube_caption:new_one"
    assert result[0].topics == ["HER2"]
    assert isinstance(result[0], CandidateSource)


@patch("discovery.connect")
@patch("discovery.fetch_catalog_page")
def test_find_new_sources_stops_when_page_fully_known(mock_fetch, mock_connect) -> None:
    conn_cm = MagicMock()
    fake_conn = MagicMock()
    fake_conn.execute.return_value.fetchall.return_value = [
        {"source_id": "youtube_caption:a"},
        {"source_id": "youtube_caption:b"},
    ]
    conn_cm.__enter__.return_value = fake_conn
    mock_connect.return_value = conn_cm

    mock_fetch.return_value = [
        {"id": "official:youtube:a", "title": "A", "youtube_url": "", "doctors": [], "tags": []},
        {"id": "official:youtube:b", "title": "B", "youtube_url": "", "doctors": [], "tags": []},
    ]

    result = find_new_sources(max_pages=5)

    assert result == []
    # only the first page should have been fetched — loop stops on a fully-known page
    assert mock_fetch.call_count == 1


@patch("discovery.connect")
@patch("discovery.fetch_catalog_page")
def test_find_new_sources_empty_catalog_returns_empty(mock_fetch, mock_connect) -> None:
    conn_cm = MagicMock()
    fake_conn = MagicMock()
    fake_conn.execute.return_value.fetchall.return_value = []
    conn_cm.__enter__.return_value = fake_conn
    mock_connect.return_value = conn_cm

    mock_fetch.return_value = []

    assert find_new_sources() == []

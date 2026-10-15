from unittest.mock import MagicMock, patch

import httpx

import discovery
from discovery import (
    CandidateSource,
    _source_id_for_clip,
    candidate_for_clip,
    clean_description,
    clip_document,
    clip_page_url,
    clip_topics,
    fetch_catalog_page,
    find_new_sources,
    is_refusal,
    known_source_ids,
    transcript_video_ids,
    unique_doctors,
)

SUMMARY = "The ASCENT trial established sacituzumab govitecan as a standard of care in mTNBC."


def _clip(video_id: str, **overrides) -> dict:
    item = {
        "id": f"official:youtube:{video_id}",
        "title": f"Clip {video_id}",
        "description": "Longer YouTube description.",
        "ai_summary": SUMMARY,
        "youtube_url": f"https://www.youtube.com/watch?v={video_id}",
        "doctors": ["Iyengar"],
        "tags": ["biomarker:TNBC", "doctor:Iyengar", "drug:Trodelvy"],
        "posted_at": "2026-06-26T14:00:00Z",
        "is_short": False,
    }
    item.update(overrides)
    return item


def _db(source_rows: list[dict], transcript_rows: list[dict] | None = None):
    conn = MagicMock()

    def execute(sql, *args):
        result = MagicMock()
        result.fetchall.return_value = (transcript_rows or []) if "chunk_count" in sql else source_rows
        return result

    conn.execute.side_effect = execute
    cm = MagicMock()
    cm.__enter__.return_value = conn
    return cm


def test_source_id_for_clip_uses_catalog_clip_type() -> None:
    assert _source_id_for_clip("official:youtube:abc123") == "catalog_clip:abc123"


def test_clip_page_url_points_at_platform_clip_page() -> None:
    url = clip_page_url(_clip("_mPwb4EzhwE"))
    assert url == f"{discovery.PLATFORM_APP_URL}/catalog/clip/_mPwb4EzhwE"


def test_clip_page_url_falls_back_to_youtube_for_unknown_ids() -> None:
    item = {"id": "linkedin:post:1", "youtube_url": "https://example.com/v"}
    assert clip_page_url(item) == "https://example.com/v"


def test_is_refusal_matches_mediahub_refusals() -> None:
    assert is_refusal("I appreciate you sharing this, but I'm unable to generate a medical education summary.")
    assert not is_refusal(SUMMARY)
    assert not is_refusal(None)


def test_unique_doctors_drops_spelling_variants() -> None:
    assert unique_doctors(["O'shaughnessy", "Oshaughnessy", "Iyengar"]) == ["O'shaughnessy", "Iyengar"]


def test_clip_topics_skips_doctor_tags() -> None:
    assert clip_topics(["biomarker:TNBC", "doctor:Iyengar", "drug:Trodelvy", "drug:Trodelvy"]) == [
        "TNBC",
        "Trodelvy",
    ]


def test_clip_document_includes_summary_and_description() -> None:
    text = clip_document(_clip("abc"), ["Iyengar"], ["TNBC"])
    assert text.startswith("Clip abc")
    assert "Doctors: Iyengar" in text
    assert "Topics: TNBC" in text
    assert "Posted: 2026-06-26" in text
    assert f"Summary: {SUMMARY}" in text
    assert "Description: Longer YouTube description." in text


def test_clip_document_skips_refusal_summary_and_uses_description() -> None:
    item = _clip("abc", ai_summary="Unable to generate a medical education description for this.")
    text = clip_document(item, [], [])
    assert "Summary:" not in text
    assert "Description: Longer YouTube description." in text


YOUTUBE_DESCRIPTION = """Can neoadjuvant T-DXd improve pCR?

Dr. Abi Siva and Dr. Carey Anders discuss DESTINY-Breast11.

Subscribe for more expert oncology discussions.

#AbiSiva #CareyAnders #DESTINYBreast11 #CHM
–

Thanks for watching!

Our podcasts are also available on:
 • Spotify - https://spotf.fi/chm-podcast

–

Community Health Media (CHM) is your full service healthcare communications partner.

Learn more about us here - https://communityhealth.media"""


def test_clean_description_drops_channel_footer_and_hashtags() -> None:
    assert clean_description(YOUTUBE_DESCRIPTION) == (
        "Can neoadjuvant T-DXd improve pCR?\n\nDr. Abi Siva and Dr. Carey Anders discuss DESTINY-Breast11."
    )


def test_clip_document_never_includes_chm_blurb() -> None:
    text = clip_document(_clip("abc", ai_summary="", description=YOUTUBE_DESCRIPTION), [], [])
    assert "DESTINY-Breast11" in text
    assert "Community Health Media" not in text
    assert "Spotify" not in text


def test_clip_document_empty_when_description_is_only_footer() -> None:
    footer = YOUTUBE_DESCRIPTION.split("–", 1)[1]
    assert clip_document(_clip("abc", ai_summary="", description=footer), [], []) == ""


def test_clip_document_empty_when_no_usable_text() -> None:
    assert clip_document(_clip("abc", ai_summary="", description="  "), [], []) == ""


def test_candidate_for_clip_skips_shorts() -> None:
    assert candidate_for_clip(_clip("abc", is_short=True)) is None


def test_candidate_for_clip_carries_text_and_youtube_id() -> None:
    candidate = candidate_for_clip(_clip("abc"))
    assert isinstance(candidate, CandidateSource)
    assert candidate.source_type == "catalog_clip"
    assert candidate.external_id == "abc"
    assert candidate.topics == ["TNBC", "Trodelvy"]
    assert SUMMARY in candidate.text


def test_known_source_ids_reads_from_sources_table() -> None:
    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = [
        {"source_id": "catalog_clip:a"},
        {"source_id": "curated_doc:site/about.md"},
    ]
    assert known_source_ids(conn) == {"catalog_clip:a", "curated_doc:site/about.md"}


def test_transcript_video_ids_reads_caption_ids_and_external_ids() -> None:
    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = [
        {"source_id": "youtube_caption:vid1", "external_id": None},
        {"source_id": "curated_doc:podcast6_edit.txt", "external_id": "vid2"},
    ]
    assert transcript_video_ids(conn) == {"vid1", "vid2"}


def test_fetch_catalog_page_calls_expected_endpoint() -> None:
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.json.return_value = {"items": [{"id": "official:youtube:x", "title": "T"}]}
    mock_client.get.return_value = mock_response

    items = fetch_catalog_page(limit=10, offset=0, client=mock_client)

    assert items == [{"id": "official:youtube:x", "title": "T"}]
    assert mock_client.get.call_args.kwargs["params"] == {"limit": 10, "offset": 0, "sort_by": "recent"}


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
def test_find_new_sources_skips_known_and_transcribed_videos(mock_fetch, mock_connect) -> None:
    mock_connect.return_value = _db(
        [{"source_id": "catalog_clip:known"}],
        [{"source_id": "curated_doc:podcast6_edit.txt", "external_id": "podcast"}],
    )
    mock_fetch.return_value = [_clip("known"), _clip("podcast"), _clip("new_one")]

    result = find_new_sources(page_size=50)

    assert [c.source_id for c in result] == ["catalog_clip:new_one"]
    assert mock_fetch.call_count == 1


@patch("discovery.connect")
@patch("discovery.fetch_catalog_page")
def test_find_new_sources_full_sync_includes_known_clips(mock_fetch, mock_connect) -> None:
    mock_connect.return_value = _db([{"source_id": "catalog_clip:known"}])
    mock_fetch.return_value = [_clip("known"), _clip("new_one")]

    result = find_new_sources(page_size=50, full_sync=True)

    assert [c.source_id for c in result] == ["catalog_clip:known", "catalog_clip:new_one"]


@patch("discovery.connect")
@patch("discovery.fetch_catalog_page")
def test_find_new_sources_reads_every_page_and_dedupes_repeats(mock_fetch, mock_connect) -> None:
    mock_connect.return_value = _db([{"source_id": "catalog_clip:a"}, {"source_id": "catalog_clip:b"}])
    mock_fetch.side_effect = [
        [_clip("a"), _clip("b")],  # fully known page does not stop paging
        [_clip("b"), _clip("c")],  # "b" repeated across pages
        [_clip("d")],  # short page ends paging
    ]

    result = find_new_sources(page_size=2)

    assert [c.source_id for c in result] == ["catalog_clip:c", "catalog_clip:d"]
    assert mock_fetch.call_count == 3


@patch("discovery.connect")
@patch("discovery.fetch_catalog_page")
def test_find_new_sources_empty_catalog_returns_empty(mock_fetch, mock_connect) -> None:
    mock_connect.return_value = _db([])
    mock_fetch.return_value = []

    assert find_new_sources() == []

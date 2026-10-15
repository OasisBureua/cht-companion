from unittest.mock import MagicMock, patch

import pytest
from youtube_transcript_api._errors import IpBlocked, NoTranscriptFound, TranscriptsDisabled

from transcripts import (
    TranscriptFetchError,
    TranscriptUnavailable,
    fetch_youtube_transcript,
    youtube_id_from_source,
)


def test_youtube_id_from_source_id() -> None:
    assert youtube_id_from_source("youtube_caption:abc123") == "abc123"


def test_youtube_id_from_watch_url() -> None:
    assert youtube_id_from_source("other", "https://www.youtube.com/watch?v=abc123&t=10") == "abc123"


def test_youtube_id_missing_raises() -> None:
    with pytest.raises(TranscriptUnavailable):
        youtube_id_from_source("catalog_clip:nope", "")


@patch("transcripts.YouTubeTranscriptApi")
def test_fetch_joins_cues(mock_api_cls) -> None:
    mock_api_cls.return_value.fetch.return_value = [
        MagicMock(text=" Hello "),
        MagicMock(text=""),
        MagicMock(text="world"),
    ]
    assert fetch_youtube_transcript("abc") == "Hello\nworld"
    mock_api_cls.return_value.fetch.assert_called_once_with("abc", languages=["en"])


@patch("transcripts.YouTubeTranscriptApi")
def test_fetch_empty_transcript_is_unavailable(mock_api_cls) -> None:
    mock_api_cls.return_value.fetch.return_value = [MagicMock(text="  ")]
    with pytest.raises(TranscriptUnavailable, match="empty transcript"):
        fetch_youtube_transcript("abc")


@patch("transcripts.YouTubeTranscriptApi")
def test_fetch_disabled_captions_are_permanent(mock_api_cls) -> None:
    mock_api_cls.return_value.fetch.side_effect = TranscriptsDisabled("abc")
    with pytest.raises(TranscriptUnavailable):
        fetch_youtube_transcript("abc")


@patch("transcripts.YouTubeTranscriptApi")
def test_fetch_no_english_track_is_permanent(mock_api_cls) -> None:
    mock_api_cls.return_value.fetch.side_effect = NoTranscriptFound("abc", ["en"], "none")
    with pytest.raises(TranscriptUnavailable):
        fetch_youtube_transcript("abc")


@patch("transcripts.YouTubeTranscriptApi")
def test_fetch_ip_block_is_retryable(mock_api_cls) -> None:
    mock_api_cls.return_value.fetch.side_effect = IpBlocked("abc")
    with pytest.raises(TranscriptFetchError):
        fetch_youtube_transcript("abc")

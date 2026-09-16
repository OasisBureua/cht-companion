from unittest.mock import MagicMock, patch

from captions import CaptionTrack, has_human_authored_captions, list_caption_tracks


def _mock_youtube_client(items: list[dict]) -> MagicMock:
    client = MagicMock()
    client.captions.return_value.list.return_value.execute.return_value = {"items": items}
    return client


@patch("captions._client")
def test_list_caption_tracks_parses_response(mock_client_fn) -> None:
    mock_client_fn.return_value = _mock_youtube_client(
        [
            {"id": "c1", "snippet": {"language": "en", "trackKind": "ASR"}},
            {"id": "c2", "snippet": {"language": "es", "trackKind": "standard"}},
        ]
    )
    tracks = list_caption_tracks("vid123")
    assert tracks == [
        CaptionTrack(caption_id="c1", language="en", kind="asr"),
        CaptionTrack(caption_id="c2", language="es", kind="standard"),
    ]


@patch("captions._client")
def test_has_human_authored_captions_true_when_standard_present(mock_client_fn) -> None:
    mock_client_fn.return_value = _mock_youtube_client(
        [{"id": "c1", "snippet": {"language": "en", "trackKind": "standard"}}]
    )
    assert has_human_authored_captions("vid123") is True


@patch("captions._client")
def test_has_human_authored_captions_false_when_only_asr(mock_client_fn) -> None:
    # matches what was confirmed against 5 real catalog videos this session
    mock_client_fn.return_value = _mock_youtube_client(
        [{"id": "c1", "snippet": {"language": "en", "trackKind": "ASR"}}]
    )
    assert has_human_authored_captions("vid123") is False


@patch("captions._client")
def test_has_human_authored_captions_false_when_no_tracks(mock_client_fn) -> None:
    mock_client_fn.return_value = _mock_youtube_client([])
    assert has_human_authored_captions("vid123") is False

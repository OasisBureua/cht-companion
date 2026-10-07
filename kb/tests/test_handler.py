import json
from unittest.mock import patch

from handler import handler


def test_schedule_event_is_not_embedded() -> None:
    result = handler({"action": "scheduled_refresh", "source": "eventbridge.schedule"}, None)
    assert result["ok"] is False
    assert "enqueue function" in result["message"]


def test_unrecognized_event_falls_back_to_scaffold_response() -> None:
    result = handler({"foo": "bar"}, None)
    assert result["ok"] is True
    assert "scaffold" in result["message"]


@patch("handler.ingest_source")
def test_direct_invoke_missing_fields_returns_error(mock_ingest) -> None:
    result = handler({"source_id": "x"}, None)
    assert result["ok"] is False
    mock_ingest.assert_not_called()


@patch("handler.ingest_source")
def test_direct_invoke_calls_ingest(mock_ingest) -> None:
    from ingest import IngestResult

    mock_ingest.return_value = IngestResult(
        source_id="youtube_caption:abc", chunks_total=3, chunks_written=3, chunks_skipped=0
    )
    event = {
        "source_id": "youtube_caption:abc",
        "source_type": "youtube_caption",
        "title": "Test",
        "url": "https://youtube.com/watch?v=abc",
        "text": "some transcript text",
    }
    result = handler(event, None)
    assert result["ok"] is True
    assert result["result"]["chunks_written"] == 3
    mock_ingest.assert_called_once()


@patch("handler.ingest_source")
def test_sqs_batch_processes_each_record(mock_ingest) -> None:
    from ingest import IngestResult

    mock_ingest.return_value = IngestResult(
        source_id="youtube_caption:abc", chunks_total=1, chunks_written=1, chunks_skipped=0
    )
    event = {
        "Records": [
            {
                "body": json.dumps(
                    {
                        "source_id": "youtube_caption:abc",
                        "source_type": "youtube_caption",
                        "title": "Test",
                        "url": "https://youtube.com/watch?v=abc",
                        "text": "some transcript text",
                    }
                )
            }
        ]
    }
    result = handler(event, None)
    assert result["ok"] is True
    assert len(result["results"]) == 1


@patch("handler.ingest_source")
@patch("handler.fetch_youtube_transcript")
def test_sqs_without_text_fetches_transcript(mock_fetch, mock_ingest) -> None:
    from ingest import IngestResult

    mock_fetch.return_value = "fetched caption text"
    mock_ingest.return_value = IngestResult(
        source_id="youtube_caption:abc", chunks_total=1, chunks_written=1, chunks_skipped=0
    )
    event = {
        "Records": [
            {
                "body": json.dumps(
                    {
                        "source_id": "youtube_caption:abc",
                        "source_type": "youtube_caption",
                        "title": "Test",
                        "url": "https://youtube.com/watch?v=abc",
                        "content_date": "2026-09-01T00:00:00Z",
                    }
                )
            }
        ]
    }
    result = handler(event, None)
    assert result["ok"] is True
    mock_fetch.assert_called_once_with("abc")
    source, text = mock_ingest.call_args.args
    assert text == "fetched caption text"
    assert source.content_date.isoformat() == "2026-09-01"


@patch("handler.ingest_source")
@patch("handler.fetch_youtube_transcript")
def test_sqs_permanent_transcript_miss_is_recorded_not_raised(mock_fetch, mock_ingest) -> None:
    from transcripts import TranscriptUnavailable

    mock_fetch.side_effect = TranscriptUnavailable("no transcript for abc")
    event = {
        "Records": [
            {
                "body": json.dumps(
                    {
                        "source_id": "youtube_caption:abc",
                        "source_type": "youtube_caption",
                        "title": "Test",
                        "url": "https://youtube.com/watch?v=abc",
                    }
                )
            }
        ]
    }
    result = handler(event, None)
    assert result["ok"] is False
    assert "no transcript" in result["results"][0]["error"]
    mock_ingest.assert_not_called()


@patch("handler.fetch_youtube_transcript")
def test_sqs_transient_transcript_failure_propagates(mock_fetch) -> None:
    from transcripts import TranscriptFetchError

    mock_fetch.side_effect = TranscriptFetchError("blocked")
    event = {
        "Records": [
            {
                "body": json.dumps(
                    {
                        "source_id": "youtube_caption:abc",
                        "source_type": "youtube_caption",
                        "title": "Test",
                        "url": "https://youtube.com/watch?v=abc",
                    }
                )
            }
        ]
    }
    try:
        handler(event, None)
    except TranscriptFetchError:
        pass
    else:
        raise AssertionError("transient transcript failures must fail the invocation so SQS retries")


def _s3_event(key: str, bucket: str = "cht-dev-companion-raw") -> dict:
    return {
        "Records": [
            {
                "eventSource": "aws:s3",
                "s3": {"bucket": {"name": bucket}, "object": {"key": key}},
            }
        ]
    }


@patch("handler.ingest_source")
@patch("handler.load_document")
def test_s3_upload_ingests_curated_doc(mock_load, mock_ingest, monkeypatch) -> None:
    from ingest import IngestResult

    monkeypatch.setenv("RAW_BUCKET_NAME", "cht-dev-companion-raw")
    mock_load.return_value = ("Enhertu is a HER2 antibody drug conjugate.", "Enhertu label")
    mock_ingest.return_value = IngestResult(
        source_id="curated_doc:labels/enhertu-label.pdf",
        chunks_total=1,
        chunks_written=1,
        chunks_skipped=0,
    )

    result = handler(_s3_event("labels/enhertu-label.pdf"), None)

    assert result["ok"] is True
    assert result["message"] == "cht-companion-kb s3 drop"
    mock_load.assert_called_once_with("cht-dev-companion-raw", "labels/enhertu-label.pdf")
    source, text = mock_ingest.call_args.args
    assert source.source_type == "curated_doc"
    assert source.source_id == "curated_doc:labels/enhertu-label.pdf"
    assert source.url == "s3://cht-dev-companion-raw/labels/enhertu-label.pdf"
    assert text.startswith("Enhertu")


@patch("handler.ingest_source")
@patch("handler.load_document")
def test_s3_markdown_front_matter_sets_citation_url(mock_load, mock_ingest, monkeypatch) -> None:
    from ingest import IngestResult

    monkeypatch.setenv("RAW_BUCKET_NAME", "cht-dev-companion-raw")
    mock_load.return_value = (
        "---\ntitle: About CHM\nurl: https://devapp.communityhealth.media/about\n---\nCHM is a partner.",
        "about chm",
    )
    mock_ingest.return_value = IngestResult(
        source_id="curated_doc:site/about-chm.md", chunks_total=1, chunks_written=1, chunks_skipped=0
    )

    handler(_s3_event("site/about-chm.md"), None)

    source, text = mock_ingest.call_args.args
    assert source.title == "About CHM"
    assert source.url == "https://devapp.communityhealth.media/about"
    assert text == "CHM is a partner."


@patch("handler.ingest_source")
@patch("handler.load_document")
def test_s3_podcast_title_comes_from_mapping(mock_load, mock_ingest, monkeypatch) -> None:
    from ingest import IngestResult
    from podcast_metadata import podcast_title, podcast_url

    monkeypatch.setenv("RAW_BUCKET_NAME", "cht-dev-companion-raw")
    mock_load.return_value = ("transcript text", "podcast6 edit")
    mock_ingest.return_value = IngestResult(
        source_id="curated_doc:podcast6_edit.txt",
        chunks_total=1,
        chunks_written=1,
        chunks_skipped=0,
    )

    handler(_s3_event("podcast6_edit.txt"), None)

    source, _text = mock_ingest.call_args.args
    assert source.title == podcast_title("podcast6_edit.txt")
    assert source.url == podcast_url("podcast6_edit.txt")
    assert "podcast6 edit" not in source.title


@patch("handler.ingest_source")
@patch("handler.load_document")
def test_s3_decodes_object_key(mock_load, mock_ingest, monkeypatch) -> None:
    from ingest import IngestResult

    monkeypatch.setenv("RAW_BUCKET_NAME", "cht-dev-companion-raw")
    mock_load.return_value = ("notes", "Enhertu label")
    mock_ingest.return_value = IngestResult(
        source_id="curated_doc:labels/Enhertu label.pdf",
        chunks_total=1,
        chunks_written=1,
        chunks_skipped=0,
    )

    handler(_s3_event("labels/Enhertu+label.pdf"), None)

    mock_load.assert_called_once_with("cht-dev-companion-raw", "labels/Enhertu label.pdf")


@patch("handler.ingest_source")
@patch("handler.load_document")
def test_s3_unsupported_file_is_skipped(mock_load, mock_ingest, monkeypatch) -> None:
    from documents import UnsupportedDocument

    monkeypatch.setenv("RAW_BUCKET_NAME", "cht-dev-companion-raw")
    mock_load.side_effect = UnsupportedDocument("unsupported file type for photo.png")

    result = handler(_s3_event("photo.png"), None)

    assert result["ok"] is True
    assert result["results"][0]["skipped"] is True
    mock_ingest.assert_not_called()


@patch("handler.load_document")
def test_s3_wrong_bucket_is_skipped(mock_load, monkeypatch) -> None:
    monkeypatch.setenv("RAW_BUCKET_NAME", "cht-dev-companion-raw")

    result = handler(_s3_event("notes.txt", bucket="other-bucket"), None)

    assert result["results"][0]["skipped"] is True
    mock_load.assert_not_called()

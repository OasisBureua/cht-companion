import json
from unittest.mock import patch

from handler import handler


def test_scheduled_event_is_a_noop() -> None:
    result = handler({"source": "aws.events"}, None)
    assert result["ok"] is True
    assert "cht-companion-kb" in result["message"]


def test_real_eventbridge_rule_payload_is_a_noop() -> None:
    # Actual payload from cht-dev-companion-kb-schedule (confirmed live via
    # `aws events list-targets-by-rule`), not the generic "aws.events" shape.
    result = handler({"action": "scheduled_refresh", "source": "eventbridge.schedule"}, None)
    assert result["ok"] is True
    assert "no trigger source wired yet" in result["message"]


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

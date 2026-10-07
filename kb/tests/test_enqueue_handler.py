from unittest.mock import patch

import pytest

from enqueue_handler import handler


def _candidate():
    from discovery import CandidateSource

    return CandidateSource(
        source_id="catalog_clip:abc",
        source_type="catalog_clip",
        title="Test",
        url="https://devapp.communityhealth.media/catalog/clip/abc",
        doctors=[],
        topics=[],
        posted_at=None,
        external_id="abc",
        text="Test\n\nSummary: something",
    )


@patch("enqueue_handler.enqueue_candidates")
@patch("enqueue_handler.find_new_sources")
def test_scheduled_event_enqueues_discovery_candidates(mock_find, mock_enqueue) -> None:
    mock_find.return_value = [_candidate()]
    mock_enqueue.return_value = ["catalog_clip:abc"]
    result = handler({"source": "aws.events"}, None)
    assert result["ok"] is True
    assert result["full_sync"] is False
    assert result["candidates_found"] == 1
    assert result["enqueued"] == 1
    assert result["candidate_source_ids"] == ["catalog_clip:abc"]
    mock_find.assert_called_once_with(full_sync=False)
    mock_enqueue.assert_called_once_with(mock_find.return_value)


@patch("enqueue_handler.enqueue_candidates")
@patch("enqueue_handler.find_new_sources")
def test_full_sync_flag_is_passed_to_discovery(mock_find, mock_enqueue) -> None:
    mock_find.return_value = []
    mock_enqueue.return_value = []
    result = handler({"source": "aws.events", "full_sync": True}, None)
    assert result["full_sync"] is True
    mock_find.assert_called_once_with(full_sync=True)


@patch("enqueue_handler.find_new_sources")
def test_real_eventbridge_rule_payload_runs_discovery(mock_find) -> None:
    mock_find.return_value = []
    result = handler({"action": "scheduled_refresh", "source": "eventbridge.schedule"}, None)
    assert result["ok"] is True
    assert result["candidates_found"] == 0
    assert result["enqueued"] == 0
    assert "enqueued for embedding" in result["message"]


@patch("enqueue_handler.enqueue_candidates")
@patch("enqueue_handler.find_new_sources")
def test_scheduled_enqueue_failure_fails_the_invocation(mock_find, mock_enqueue) -> None:
    from enqueue import EnqueueError

    mock_find.return_value = [_candidate()]
    mock_enqueue.side_effect = EnqueueError("queue down")
    with pytest.raises(EnqueueError, match="queue down"):
        handler({"source": "aws.events"}, None)


@patch("enqueue_handler.find_new_sources")
def test_scheduled_discovery_failure_does_not_crash(mock_find) -> None:
    mock_find.side_effect = RuntimeError("catalog unreachable")
    result = handler({"source": "aws.events"}, None)
    assert result["ok"] is False
    assert "catalog unreachable" in result["error"]


def test_sqs_event_is_rejected() -> None:
    with pytest.raises(RuntimeError, match="does not consume SQS"):
        handler({"Records": [{"body": "{}"}]}, None)

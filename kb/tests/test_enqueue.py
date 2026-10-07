import json
from unittest.mock import MagicMock, patch

import pytest

from discovery import CandidateSource
from enqueue import EnqueueError, candidate_message, enqueue_candidates


def _candidate(source_id: str = "catalog_clip:abc", text: str = "Clip abc\n\nSummary: HER2-low") -> CandidateSource:
    video_id = source_id.split(":")[-1]
    return CandidateSource(
        source_id=source_id,
        source_type="catalog_clip",
        title="A clip",
        url=f"https://devapp.communityhealth.media/catalog/clip/{video_id}",
        doctors=["Dr. Test"],
        topics=["HER2"],
        posted_at="2026-09-01T00:00:00Z",
        external_id=video_id,
        text=text,
    )


def test_candidate_message_carries_clip_text() -> None:
    body = candidate_message(_candidate())
    assert body["source_id"] == "catalog_clip:abc"
    assert body["source_type"] == "catalog_clip"
    assert body["external_id"] == "abc"
    assert body["content_date"] == "2026-09-01T00:00:00Z"
    assert body["text"] == "Clip abc\n\nSummary: HER2-low"


def test_candidate_message_without_text_omits_it() -> None:
    assert "text" not in candidate_message(_candidate(text=""))


def test_enqueue_empty_does_not_need_a_queue(monkeypatch) -> None:
    monkeypatch.delenv("KB_INGEST_QUEUE_URL", raising=False)
    assert enqueue_candidates([]) == []


def test_enqueue_requires_queue_url(monkeypatch) -> None:
    monkeypatch.delenv("KB_INGEST_QUEUE_URL", raising=False)
    with pytest.raises(EnqueueError, match="KB_INGEST_QUEUE_URL"):
        enqueue_candidates([_candidate()])


@patch("enqueue._sqs_client")
def test_enqueue_sends_batches(mock_client_fn, monkeypatch) -> None:
    monkeypatch.setenv("KB_INGEST_QUEUE_URL", "https://sqs.example/queue")
    client = MagicMock()
    client.send_message_batch.return_value = {"Failed": []}
    mock_client_fn.return_value = client

    candidates = [_candidate(f"catalog_clip:v{i}") for i in range(11)]
    sent = enqueue_candidates(candidates)

    assert sent == [c.source_id for c in candidates]
    assert client.send_message_batch.call_count == 2
    first_entries = client.send_message_batch.call_args_list[0].kwargs["Entries"]
    assert len(first_entries) == 10
    assert json.loads(first_entries[0]["MessageBody"])["source_id"] == "catalog_clip:v0"


@patch("enqueue._sqs_client")
def test_enqueue_raises_when_sqs_rejects(mock_client_fn, monkeypatch) -> None:
    monkeypatch.setenv("KB_INGEST_QUEUE_URL", "https://sqs.example/queue")
    client = MagicMock()
    client.send_message_batch.return_value = {"Failed": [{"Id": "0", "Code": "AccessDenied"}]}
    mock_client_fn.return_value = client

    with pytest.raises(EnqueueError, match="AccessDenied"):
        enqueue_candidates([_candidate()])

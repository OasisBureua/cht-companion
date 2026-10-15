"""Enqueue catalog candidates onto the KB ingest queue (CHAT-19).

Each message carries the clip's summary document in `text` (a few KB, well
under the 256KB SQS limit), so the embed worker never fetches from YouTube.
"""

from __future__ import annotations

import json
import os

import boto3

from discovery import CandidateSource

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
QUEUE_URL_ENV = "KB_INGEST_QUEUE_URL"
_BATCH_SIZE = 10


class EnqueueError(Exception):
    pass


def _sqs_client():
    return boto3.client("sqs", region_name=AWS_REGION)


def candidate_message(candidate: CandidateSource) -> dict:
    """SQS body the embed worker ingests as-is."""
    body = {
        "source_id": candidate.source_id,
        "source_type": candidate.source_type,
        "title": candidate.title,
        "url": candidate.url,
        "external_id": candidate.external_id or candidate.source_id.split(":", 1)[-1],
        "doctors": candidate.doctors,
        "topics": candidate.topics,
        "content_date": candidate.posted_at,
    }
    if candidate.text:
        body["text"] = candidate.text
    return body


def enqueue_candidates(candidates: list[CandidateSource]) -> list[str]:
    """Send one message per candidate. Returns the source ids accepted by SQS.

    An empty list is a no-op (no queue URL required) so a scheduled run that
    finds nothing still succeeds in local tests and on a quiet day.
    """
    if not candidates:
        return []

    queue_url = os.environ.get(QUEUE_URL_ENV, "").strip()
    if not queue_url:
        raise EnqueueError(f"{QUEUE_URL_ENV} is not set")

    client = _sqs_client()
    sent: list[str] = []
    for start in range(0, len(candidates), _BATCH_SIZE):
        batch = candidates[start : start + _BATCH_SIZE]
        entries = [
            {"Id": str(i), "MessageBody": json.dumps(candidate_message(candidate))}
            for i, candidate in enumerate(batch)
        ]
        response = client.send_message_batch(QueueUrl=queue_url, Entries=entries)
        failed = response.get("Failed") or []
        if failed:
            raise EnqueueError(f"SQS rejected {len(failed)} message(s): {failed}")
        sent.extend(candidate.source_id for candidate in batch)

    return sent

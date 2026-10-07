"""cht-companion-kb embed worker (SQS / S3 / direct invoke) — CHAT-17/20/21.

Catalog discovery lives in enqueue_handler.py. This function only embeds:

  - {"Records": [{"body": "<json SourceIngestRequest>"}]}              -> SQS: one source per record
  - {"Records": [{"eventSource": "aws:s3", "s3": {...}}]}              -> drop-zone upload (PDF, docx, text)
  - {"source_id": ..., "source_type": ..., ...}                        -> direct invoke (bootstrap, manual)

`text` is required only when it cannot be fetched. A youtube_caption message
without `text` triggers a transcript fetch. A permanent miss is reported and
the message is deleted. A transient fetch failure is raised so SQS retries.
Embeddings are amazon.titan-embed-text-v2:0 via Bedrock.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date
from typing import Any
from urllib.parse import unquote_plus

from documents import (
    DocumentUnavailable,
    EmptyDocument,
    UnsupportedDocument,
    load_document,
    source_id_for_key,
    split_front_matter,
)
from embedding import EMBEDDING_MODEL
from ingest import IngestResult, ingest_source
from podcast_metadata import lookup_podcast, podcast_title, podcast_url
from store import SourceInput
from transcripts import TranscriptUnavailable, fetch_youtube_transcript, youtube_id_from_source

logger = logging.getLogger("cht-companion-kb")
logging.basicConfig(level=logging.INFO)

REQUIRED_FIELDS = ("source_id", "source_type", "title", "url")


def _as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def _resolve_text(payload: dict[str, Any]) -> str:
    text = (payload.get("text") or "").strip()
    if text:
        return text
    if payload.get("source_type") != "youtube_caption":
        raise ValueError("missing required fields: ['text']")

    video_id = youtube_id_from_source(payload["source_id"], payload.get("url") or "")
    try:
        return fetch_youtube_transcript(video_id)
    except TranscriptUnavailable as exc:
        raise ValueError(str(exc)) from exc


def _source_request_to_input(payload: dict[str, Any]) -> tuple[SourceInput, str]:
    missing = [f for f in REQUIRED_FIELDS if not payload.get(f)]
    if missing:
        raise ValueError(f"missing required fields: {missing}")

    source = SourceInput(
        source_id=payload["source_id"],
        source_type=payload["source_type"],
        title=payload["title"],
        url=payload["url"],
        embedding_model=EMBEDDING_MODEL,
        playlist_url=payload.get("playlist_url"),
        external_id=payload.get("external_id"),
        doctors=payload.get("doctors") or [],
        topics=payload.get("topics") or [],
        content_date=_as_date(payload.get("content_date")),
    )
    return source, _resolve_text(payload)


def _ingest_result_to_dict(result: IngestResult) -> dict[str, Any]:
    return {
        "source_id": result.source_id,
        "chunks_total": result.chunks_total,
        "chunks_written": result.chunks_written,
        "chunks_skipped": result.chunks_skipped,
        "error": result.error,
    }


def _handle_source_request(payload: dict[str, Any]) -> dict[str, Any]:
    source, text = _source_request_to_input(payload)
    result = ingest_source(source, text)
    return _ingest_result_to_dict(result)


def _is_s3_event(event: dict[str, Any]) -> bool:
    records = event.get("Records") or []
    if not records:
        return False
    first = records[0]
    return first.get("eventSource") == "aws:s3" or ("s3" in first and "body" not in first)


def _handle_s3_record(record: dict[str, Any]) -> dict[str, Any]:
    bucket = record["s3"]["bucket"]["name"]
    key = unquote_plus(record["s3"]["object"]["key"])
    expected = os.environ.get("RAW_BUCKET_NAME", "").strip()
    if expected and bucket != expected:
        return {"skipped": True, "key": key, "reason": f"unexpected bucket {bucket}"}
    if key.endswith("/"):
        return {"skipped": True, "key": key, "reason": "folder marker"}

    try:
        text, title = load_document(bucket, key)
    except UnsupportedDocument as exc:
        logger.info("s3_skip_unsupported", extra={"key": key, "error": str(exc)})
        return {"skipped": True, "key": key, "reason": str(exc)}
    except (EmptyDocument, DocumentUnavailable) as exc:
        logger.error("s3_document_unusable", extra={"key": key, "error": str(exc)})
        return {"key": key, "error": str(exc)}

    front, text = split_front_matter(text)
    if not text:
        return {"key": key, "error": f"no text after front matter in {key}"}

    meta = lookup_podcast(key)
    source = SourceInput(
        source_id=source_id_for_key(key),
        source_type="curated_doc",
        title=podcast_title(key) or front.get("title") or title,
        url=podcast_url(key) or front.get("url") or f"s3://{bucket}/{key}",
        embedding_model=EMBEDDING_MODEL,
        external_id=(meta or {}).get("youtube_id") or key,
        doctors=(meta or {}).get("doctors") or [],
        topics=(meta or {}).get("topics") or [],
    )
    result = _ingest_result_to_dict(ingest_source(source, text))
    result["key"] = key
    return result


def _handle_s3_event(event: dict[str, Any]) -> dict[str, Any]:
    results = [_handle_s3_record(record) for record in event["Records"]]
    ok = all(r.get("error") is None for r in results)
    return {"ok": ok, "message": "cht-companion-kb s3 drop", "results": results}


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    # S3 drop zone: ObjectCreated on the raw bucket. Checked before the SQS
    # branch because both event types use a top-level "Records" list.
    if _is_s3_event(event):
        return _handle_s3_event(event)

    # SQS: one or more source-ingest requests, each JSON-encoded in .body
    if "Records" in event:
        results = []
        for record in event["Records"]:
            body = json.loads(record["body"])
            try:
                results.append(_handle_source_request(body))
            except ValueError as exc:
                logger.error("invalid_sqs_record", extra={"error": str(exc)})
                results.append({"error": str(exc)})
        ok = all("error" not in r or r["error"] is None for r in results)
        return {"ok": ok, "message": "cht-companion-kb sqs batch", "results": results}

    if event.get("source") in ("aws.events", "eventbridge.schedule"):
        return {
            "ok": False,
            "message": "catalog discovery runs on the enqueue function, not the embed function",
        }

    # Direct invoke: bootstrap loads, manual backfill, local testing.
    if "source_id" in event:
        try:
            result = _handle_source_request(event)
            return {"ok": result.get("error") is None, "message": "cht-companion-kb direct ingest", "result": result}
        except ValueError as exc:
            return {"ok": False, "message": str(exc)}

    return {"ok": True, "message": "cht-companion-kb scaffold", "event_keys": list(event.keys())}

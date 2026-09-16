"""cht-companion-kb: chunk + embed jobs (EventBridge / SQS) — CHAT-17/20/21.

Event shapes handled:
  - {"action": "scheduled_refresh", "source": "eventbridge.schedule"}  -> the actual EventBridge rule
    payload (cht-dev-companion-kb-schedule, rate(1 day)). Runs catalog discovery (CHAT-19) and
    reports candidate sources found — does NOT enqueue them yet. See discovery.py's module
    docstring: no transcript-text source exists until YouTube channel-owner OAuth is granted
    (captions.download needs OAuth, not just an API key; cht-platform-tool's
    /catalog/transcripts/:shootId is dead code). Enqueuing now would just produce SQS
    messages this Lambda's own REQUIRED_FIELDS check rejects for missing `text`.
  - {"Records": [{"body": "<json SourceIngestRequest>"}]}              -> SQS: one source per record
  - {"source_id": ..., "source_type": ..., ...}                        -> direct invoke (bootstrap loads, manual backfill)
"""

from __future__ import annotations

import json
import logging
from typing import Any

from discovery import find_new_sources
from embedding import EMBEDDING_MODEL
from ingest import IngestResult, ingest_source
from store import SourceInput

logger = logging.getLogger("cht-companion-kb")
logging.basicConfig(level=logging.INFO)

REQUIRED_FIELDS = ("source_id", "source_type", "title", "url", "text")


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
        doctors=payload.get("doctors", []),
        topics=payload.get("topics", []),
        content_date=payload.get("content_date"),
    )
    return source, payload["text"]


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


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
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

    # EventBridge scheduled trigger. Real rule payload is
    # {"action": "scheduled_refresh", "source": "eventbridge.schedule"} (confirmed live
    # via `aws events list-targets-by-rule --rule cht-dev-companion-kb-schedule`), not the
    # generic "aws.events" shape a raw EventBridge-console test event uses — match both so
    # local/console testing still exercises this branch.
    if event.get("source") in ("aws.events", "eventbridge.schedule"):
        try:
            candidates = find_new_sources()
        except Exception as exc:  # noqa: BLE001 — catalog/DB failure shouldn't crash the scheduled run
            logger.error("scheduled_discovery_failed", extra={"error": str(exc)})
            return {"ok": False, "message": "cht-companion-kb scheduled discovery failed", "error": str(exc)}

        logger.info(
            "scheduled_discovery_found_candidates",
            extra={"action": event.get("action"), "count": len(candidates)},
        )
        return {
            "ok": True,
            "message": (
                f"cht-companion-kb scheduled reconcile: {len(candidates)} new catalog source(s) found, "
                "not yet enqueued — no transcript-text source wired (blocked on YouTube channel-owner "
                "OAuth, see discovery.py)"
            ),
            "candidates_found": len(candidates),
            "candidate_source_ids": [c.source_id for c in candidates],
        }

    # Direct invoke: bootstrap loads, manual backfill, local testing.
    if "source_id" in event:
        try:
            result = _handle_source_request(event)
            return {"ok": result.get("error") is None, "message": "cht-companion-kb direct ingest", "result": result}
        except ValueError as exc:
            return {"ok": False, "message": str(exc)}

    return {"ok": True, "message": "cht-companion-kb scaffold", "event_keys": list(event.keys())}

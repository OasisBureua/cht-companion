"""Catalog check for cht-companion-kb.

EventBridge invokes this function. It finds catalog clips that are not in
cht-companion-db yet and enqueues one metadata message per clip. Transcript
fetch and Titan embedding happen in handler.py, one SQS message at a time.
"""

from __future__ import annotations

import logging
from typing import Any

from discovery import find_new_sources
from enqueue import enqueue_candidates

logger = logging.getLogger("cht-companion-kb-enqueue")
logging.basicConfig(level=logging.INFO)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    if "Records" in event:
        raise RuntimeError("enqueue function does not consume SQS or S3 events")

    if event.get("source") not in ("aws.events", "eventbridge.schedule"):
        return {
            "ok": False,
            "message": "enqueue function expects the catalog schedule event",
            "event_keys": list(event.keys()),
        }

    try:
        candidates = find_new_sources()
    except Exception as exc:  # noqa: BLE001 — catalog/DB failure shouldn't crash the scheduled run
        logger.error("scheduled_discovery_failed", extra={"error": str(exc)})
        return {"ok": False, "message": "cht-companion-kb scheduled discovery failed", "error": str(exc)}

    try:
        enqueued = enqueue_candidates(candidates)
    except Exception as exc:  # noqa: BLE001 — log, then fail the invocation so EventBridge retries
        logger.error("scheduled_enqueue_failed", extra={"error": str(exc), "count": len(candidates)})
        raise

    logger.info(
        "scheduled_discovery_enqueued",
        extra={"action": event.get("action"), "count": len(candidates), "enqueued": len(enqueued)},
    )
    return {
        "ok": True,
        "message": (
            f"cht-companion-kb scheduled reconcile: {len(candidates)} new catalog source(s) found, "
            f"{len(enqueued)} enqueued for transcript fetch"
        ),
        "candidates_found": len(candidates),
        "enqueued": len(enqueued),
        "candidate_source_ids": enqueued,
    }

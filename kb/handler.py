"""cht-companion-kb: chunk + embed jobs (EventBridge / SQS)."""

from __future__ import annotations

from typing import Any


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Scaffold handler. Ingest pipeline is implemented in a later ticket."""
    return {"ok": True, "message": "cht-companion-kb scaffold", "event_keys": list(event.keys())}

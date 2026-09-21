"""Catalog discovery for scheduled ingest (CHAT-19).

Queries cht-platform-tool's public /catalog/clips endpoint for candidate
sources, filters out anything already known to cht-companion-db, and returns
a metadata-only shape ready for SQS enqueue — once a transcript source exists.

**Blocked on transcript text** (see module docstring in handler.py): YouTube's
captions.download API requires OAuth as the channel owner, not just an API
key — cht-platform-tool's YOUTUBE_API_KEY (config: youtube.apiKey) cannot
authorize it. /catalog/transcripts/:shootId is dead code on cht-platform-tool
(returns null unconditionally — "Legacy MediaHub transcript endpoint
removed"). Until channel-owner OAuth is granted (a real, external blocker,
not a code gap — flag to whoever owns the CHM YouTube channel), this module
finds *what* to ingest but has no *text* to hand the pipeline, so callers
must not enqueue these as SQS ingest requests yet: handler.py's
REQUIRED_FIELDS check would reject every one of them for a missing `text`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

from store import connect

CATALOG_BASE_URL = os.environ.get(
    "CHT_PLATFORM_CATALOG_URL", "https://devapp.communityhealth.media/api/catalog"
)
DEFAULT_PAGE_SIZE = 50


@dataclass
class CandidateSource:
    """A catalog clip not yet present in cht-companion-db. Metadata only —
    no `text` field, since no transcript source is wired yet.
    """

    source_id: str
    source_type: str
    title: str
    url: str
    doctors: list[str]
    topics: list[str]
    posted_at: str | None


def _source_id_for_clip(clip_id: str) -> str:
    """cht-platform-tool clip ids look like 'official:youtube:<video_id>'.
    Reuse the youtube_id portion so this lines up with make_source_id()'s
    'youtube_caption:<id>' scheme used by the bootstrap loader (ingest.py) —
    same video, same source_id, whichever path ingests it first.
    """
    youtube_id = clip_id.rsplit(":", 1)[-1]
    return f"youtube_caption:{youtube_id}"


def fetch_catalog_page(
    *, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0, client: httpx.Client | None = None
) -> list[dict]:
    """One page of /catalog/clips, newest first. Public endpoint, no auth."""
    owns_client = client is None
    client = client or httpx.Client(timeout=30.0)
    try:
        response = client.get(
            f"{CATALOG_BASE_URL}/clips",
            params={"limit": limit, "offset": offset, "sort_by": "recent"},
        )
        response.raise_for_status()
        return response.json().get("items", [])
    finally:
        if owns_client:
            client.close()


def known_source_ids(conn) -> set[str]:
    """Every source_id already in cht-companion-db, regardless of status —
    a rejected/soft-deleted source shouldn't be re-discovered every run.
    """
    rows = conn.execute("SELECT source_id FROM sources").fetchall()
    return {row["source_id"] for row in rows}


def find_new_sources(*, max_pages: int = 5, page_size: int = DEFAULT_PAGE_SIZE) -> list[CandidateSource]:
    """Page through the catalog (newest first) until a full page of already-known
    sources is hit — the catalog is sorted newest-first, so once discovery lands
    on ground already covered, older pages are covered too. Stops early rather
    than re-scanning the entire catalog every run.
    """
    with connect() as conn:
        existing = known_source_ids(conn)

    candidates: list[CandidateSource] = []
    with httpx.Client(timeout=30.0) as client:
        for page in range(max_pages):
            items = fetch_catalog_page(limit=page_size, offset=page * page_size, client=client)
            if not items:
                break

            page_new = []
            for item in items:
                source_id = _source_id_for_clip(item["id"])
                if source_id in existing:
                    continue
                page_new.append(
                    CandidateSource(
                        source_id=source_id,
                        source_type="youtube_caption",
                        title=item["title"],
                        url=item.get("youtube_url") or "",
                        doctors=item.get("doctors", []),
                        topics=[t.split(":", 1)[-1] for t in item.get("tags", [])],
                        posted_at=item.get("posted_at"),
                    )
                )

            candidates.extend(page_new)
            if not page_new:
                # this whole page was already known — older pages will be too
                break

    return candidates

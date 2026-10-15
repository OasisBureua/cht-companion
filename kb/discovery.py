"""Catalog discovery for scheduled ingest (CHAT-19).

Queries cht-platform-tool's public /catalog/clips endpoint (a proxy for
ContentHub, which is only reachable through the platform) and turns each
clip into a small document: title, doctors, topics, ai_summary and
description. That text travels in the SQS message, so the embed worker
never has to fetch anything from YouTube.

YouTube blocks transcript requests from AWS IPs, and captions.download
returns 403 for this channel's auto-generated tracks, so catalog clips are
embedded from their ContentHub summaries instead of transcripts. Videos that
already have a transcript in cht-companion-db (bootstrap loader or an S3
podcast upload) are skipped so one video is never cited twice.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

import httpx

from store import connect

CATALOG_BASE_URL = os.environ.get(
    "CHT_PLATFORM_CATALOG_URL", "https://devapp.communityhealth.media/api/catalog"
)
PLATFORM_APP_URL = os.environ.get(
    "CHT_PLATFORM_APP_URL", CATALOG_BASE_URL.rsplit("/api/catalog", 1)[0]
).rstrip("/")
DEFAULT_PAGE_SIZE = 50
DEFAULT_MAX_PAGES = 40

_YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")

# Refusal text MediaHub sometimes stores instead of a summary. Mirrors
# cht-platform-tool frontend/src/utils/contentHubClipText.ts.
_REFUSAL_MARKERS = (
    "unable to generate a medical education",
    "i'd be happy to create an appropriate description",
    "happy to create an appropriate description",
    "if you have a video featuring a kol",
    "healthcare professionals discussing medical topics",
    "not clinical or medical educational content",
    "voting initiative rather than clinical",
    "rather than clinical or medical educational",
)


@dataclass
class CandidateSource:
    """A catalog clip to (re)embed, with the document text to embed."""

    source_id: str
    source_type: str
    title: str
    url: str
    doctors: list[str]
    topics: list[str]
    posted_at: str | None
    external_id: str = ""
    text: str = ""


def youtube_id_for_clip(clip_id: str) -> str:
    """cht-platform-tool clip ids look like 'official:youtube:<video_id>'."""
    return clip_id.rsplit(":", 1)[-1]


def _source_id_for_clip(clip_id: str) -> str:
    return f"catalog_clip:{youtube_id_for_clip(clip_id)}"


def clip_page_url(item: dict) -> str:
    """The platform's own clip page, falling back to YouTube."""
    video_id = youtube_id_for_clip(item.get("id", ""))
    if _YOUTUBE_ID.match(video_id):
        return f"{PLATFORM_APP_URL}/catalog/clip/{video_id}"
    return item.get("youtube_url") or ""


def is_refusal(text: str | None) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    if any(marker in t for marker in _REFUSAL_MARKERS):
        return True
    return "unable to generate" in t and "medical education" in t


def _usable(text: str | None) -> str:
    t = (text or "").strip()
    return "" if is_refusal(t) else t


# Every YouTube description ends with the same channel footer (podcast links,
# then the CHM company blurb). Left in, it makes every clip match questions
# about CHM itself.
_FOOTER_STARTS = (
    "thanks for watching",
    "our podcasts are also available",
    "community health media (chm) is",
    "learn more about us",
)
_PROMO_STARTS = ("subscribe for more", "watch the full")
_SEPARATORS = {"-", "–", "—", "---", "___"}


def clean_description(text: str | None) -> str:
    """Clip description without the channel footer, hashtags or subscribe lines."""
    kept: list[str] = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        lower = stripped.lower()
        if stripped in _SEPARATORS or lower.startswith(_FOOTER_STARTS):
            break
        if lower.startswith(_PROMO_STARTS):
            continue
        words = stripped.split()
        if words and all(word.startswith("#") for word in words):
            continue
        kept.append(stripped)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


def unique_doctors(doctors: list[str]) -> list[str]:
    """Drop spelling variants such as "O'shaughnessy" / "Oshaughnessy"."""
    seen: set[str] = set()
    result: list[str] = []
    for name in doctors:
        key = re.sub(r"[^a-z]", "", (name or "").lower())
        if key and key not in seen:
            seen.add(key)
            result.append(name.strip())
    return result


def clip_topics(tags: list[str]) -> list[str]:
    topics: list[str] = []
    for tag in tags:
        if tag.startswith("doctor:"):
            continue
        topic = tag.split(":", 1)[-1].strip()
        if topic and topic not in topics:
            topics.append(topic)
    return topics


def clip_document(item: dict, doctors: list[str], topics: list[str]) -> str:
    """Text embedded for one clip. Empty when there is nothing usable."""
    summary = _usable(item.get("ai_summary") or item.get("aiSummary"))
    description = _usable(clean_description(item.get("description")))
    if not summary and not description:
        return ""

    lines = [item.get("title", "").strip()]
    if doctors:
        lines.append(f"Doctors: {', '.join(doctors)}")
    if topics:
        lines.append(f"Topics: {', '.join(topics)}")
    if item.get("posted_at"):
        lines.append(f"Posted: {item['posted_at'][:10]}")
    if summary:
        lines.append(f"\nSummary: {summary}")
    if description and description != summary:
        lines.append(f"\nDescription: {description}")
    return "\n".join(lines).strip()


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


def transcript_video_ids(conn) -> set[str]:
    """YouTube ids that already have transcript chunks from another source
    (bootstrap youtube_caption rows or S3 podcast uploads).
    """
    rows = conn.execute(
        "SELECT source_id, external_id FROM sources "
        "WHERE source_type <> 'catalog_clip' AND chunk_count > 0"
    ).fetchall()
    ids: set[str] = set()
    for row in rows:
        if row["source_id"].startswith("youtube_caption:"):
            ids.add(row["source_id"].split(":", 1)[1])
        if row.get("external_id"):
            ids.add(row["external_id"])
    return ids


def candidate_for_clip(item: dict) -> CandidateSource | None:
    if item.get("is_short"):
        return None
    doctors = unique_doctors(item.get("doctors") or [])
    topics = clip_topics(item.get("tags") or [])
    text = clip_document(item, doctors, topics)
    if not text:
        return None
    return CandidateSource(
        source_id=_source_id_for_clip(item["id"]),
        source_type="catalog_clip",
        title=item.get("title") or youtube_id_for_clip(item["id"]),
        url=clip_page_url(item),
        doctors=doctors,
        topics=topics,
        posted_at=item.get("posted_at"),
        external_id=youtube_id_for_clip(item["id"]),
        text=text,
    )


def find_new_sources(
    *,
    max_pages: int = DEFAULT_MAX_PAGES,
    page_size: int = DEFAULT_PAGE_SIZE,
    full_sync: bool = False,
) -> list[CandidateSource]:
    """Page through the whole catalog (newest first, ~10 pages today).

    Default: only clips not yet in cht-companion-db. `full_sync`: every
    clip, so edited summaries get re-embedded (unchanged chunks are skipped
    at upsert). The API's `total` is unreliable, so paging stops on a short
    or empty page.
    """
    with connect() as conn:
        existing = known_source_ids(conn)
        covered = transcript_video_ids(conn)

    candidates: list[CandidateSource] = []
    seen: set[str] = set()
    with httpx.Client(timeout=30.0) as client:
        for page in range(max_pages):
            items = fetch_catalog_page(limit=page_size, offset=page * page_size, client=client)
            for item in items:
                source_id = _source_id_for_clip(item["id"])
                if source_id in seen:
                    continue
                seen.add(source_id)
                if youtube_id_for_clip(item["id"]) in covered:
                    continue
                if source_id in existing and not full_sync:
                    continue
                candidate = candidate_for_clip(item)
                if candidate is None:
                    continue
                candidates.append(candidate)

            if len(items) < page_size:
                break

    return candidates

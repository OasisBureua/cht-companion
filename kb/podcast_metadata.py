"""Match a dropped podcast transcript to youtube_podcast_mapping.json.

The join key is the file name (`podcast6_edit.txt`). The title chat should
show is that entry's `youtube_title`, not the file name.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_MAPPING_PATH = Path(__file__).with_name("youtube_podcast_mapping.json")


@lru_cache(maxsize=1)
def _by_filename() -> dict[str, dict]:
    if not _MAPPING_PATH.exists():
        return {}
    payload = json.loads(_MAPPING_PATH.read_text())
    index: dict[str, dict] = {}
    for meta in payload.get("podcasts", {}).values():
        filename = (meta.get("transcript_file") or "").strip()
        if filename:
            index[filename] = meta
    return index


def lookup_podcast(key: str) -> dict | None:
    """Return the mapping entry for an S3 key or bare file name, if any."""
    filename = key.rsplit("/", 1)[-1]
    return _by_filename().get(filename)


def podcast_title(key: str) -> str | None:
    meta = lookup_podcast(key)
    if not meta:
        return None
    title = (meta.get("youtube_title") or "").strip()
    return title or None


def podcast_url(key: str) -> str | None:
    meta = lookup_podcast(key)
    video_id = (meta or {}).get("youtube_id") or ""
    video_id = str(video_id).strip()
    if not video_id:
        return None
    return f"https://www.youtube.com/watch?v={video_id}"

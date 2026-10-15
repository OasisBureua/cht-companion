"""YouTube transcript text for KB ingest.

captions.download (YouTube Data API) returns 403 on this channel: every
catalog video checked has only an auto-generated (ASR) track, and YouTube
will not download those unless the owner enables third-party contributions
per caption. The player caption track — the same text YouTube shows as
auto-captions — is available without that setting and without OAuth.
youtube-transcript-api reads that track.

Text is fetched in the SQS worker (one video per invocation), not in the
daily discovery run. Discovery only enqueues metadata; a full transcript
does not belong in an SQS body, and fetching 250 of them in the scheduled
Lambda would blow the timeout.
"""

from __future__ import annotations

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    AgeRestricted,
    InvalidVideoId,
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
    VideoUnplayable,
)

# Permanent misses. Retrying will not produce text, so the worker records
# the failure and deletes the SQS message instead of parking it on the DLQ.
_PERMANENT = (
    AgeRestricted,
    InvalidVideoId,
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
    VideoUnplayable,
)


class TranscriptError(Exception):
    pass


class TranscriptUnavailable(TranscriptError):
    """No usable transcript exists for this video."""


class TranscriptFetchError(TranscriptError):
    """Transient failure (blocked, throttled, unparsable). Safe to retry."""


def youtube_id_from_source(source_id: str, url: str = "") -> str:
    """Pull the video id out of `youtube_caption:<id>` or a watch URL."""
    if source_id.startswith("youtube_caption:"):
        video_id = source_id.split(":", 1)[1].strip()
        if video_id:
            return video_id

    for marker in ("v=", "youtu.be/"):
        if marker in url:
            return url.split(marker, 1)[1].split("&", 1)[0].split("?", 1)[0].strip()

    raise TranscriptUnavailable(f"no YouTube video id on source {source_id}")


def fetch_youtube_transcript(video_id: str, *, languages: tuple[str, ...] = ("en",)) -> str:
    """Plain transcript text, one cue per line. English first, then whatever
    the library falls back to within `languages`.
    """
    try:
        fetched = YouTubeTranscriptApi().fetch(video_id, languages=list(languages))
    except _PERMANENT as exc:
        raise TranscriptUnavailable(f"no transcript for {video_id}: {exc}") from exc
    except Exception as exc:
        raise TranscriptFetchError(f"transcript fetch failed for {video_id}: {exc}") from exc

    lines = []
    for snippet in fetched:
        text = (getattr(snippet, "text", "") or "").strip()
        if text:
            lines.append(text)

    if not lines:
        raise TranscriptUnavailable(f"empty transcript for {video_id}")

    return "\n".join(lines)

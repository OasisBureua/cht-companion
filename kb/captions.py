"""YouTube caption *metadata* lookup (CHAT-19/20).

captions.list works with the channel-owner OAuth credential (youtube_auth.py)
and is genuinely useful: it tells you whether a video has a human-authored
("standard") caption track vs. only an auto-generated ("asr") one, without
needing to download anything.

captions.download does NOT work for this channel's content and is
deliberately not implemented here. Confirmed against 5 real catalog videos:
every one has only an "asr" track, and YouTube's API returns 403 forbidden
on any attempt to download an ASR track unless the channel owner has
explicitly enabled "allow third-party contributions" for that specific
caption (a YouTube Studio setting, separate from API/OAuth access — owning
the channel and having a valid OAuth grant is not sufficient by itself).

CHM already has a working, unrelated transcription pipeline for this exact
problem: yt-dlp downloads the video directly (no YouTube caption API
involved at all), a local WhisperX service transcribes it (see
~/code/chm/chm-medical-chatbot/transcribe_youtube_videos.py for the
reference implementation). That pipeline runs locally, not from this Lambda
— wiring it into cht-companion-kb's ingest path is real, separate,
unscoped work (architecture question: does WhisperX get its own cloud
service, or does this stay a locally-run step feeding the same DB?). Not
addressed in this module.
"""

from __future__ import annotations

from dataclasses import dataclass

import googleapiclient.discovery
import googleapiclient.errors

from youtube_auth import get_credentials


class CaptionFetchError(Exception):
    pass


@dataclass
class CaptionTrack:
    caption_id: str
    language: str
    kind: str  # 'standard' (human-authored) | 'asr' (auto-generated)


def _client():
    credentials = get_credentials()
    return googleapiclient.discovery.build("youtube", "v3", credentials=credentials, cache_discovery=False)


def list_caption_tracks(video_id: str) -> list[CaptionTrack]:
    """Metadata only (language, kind, id) — no caption text. Confirmed working
    against real catalog videos with the channel-owner OAuth credential.
    """
    try:
        response = _client().captions().list(part="snippet", videoId=video_id).execute()
    except googleapiclient.errors.HttpError as exc:
        raise CaptionFetchError(f"captions.list failed for {video_id}: {exc}") from exc

    return [
        CaptionTrack(
            caption_id=item["id"],
            language=item["snippet"]["language"],
            kind=item["snippet"]["trackKind"].lower(),
        )
        for item in response.get("items", [])
    ]


def has_human_authored_captions(video_id: str) -> bool:
    """True if the video has at least one 'standard' (not ASR) track — the
    only kind captions.download can reliably fetch without extra per-video
    permission from the channel owner.
    """
    return any(t.kind == "standard" for t in list_caption_tracks(video_id))

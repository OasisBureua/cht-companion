"""Load the CHAT-4 bootstrap transcript set into cht-companion-db (CHAT-22).

One-time dev bootstrap, not the ongoing ingest path. Source: youtube_podcast_mapping.json
+ raw transcript .txt files pulled off the legacy chmbot EC2 box (Uche's SCRUM-194
comment: "move as-is" bucket). Requires DATABASE_URL and Bedrock credentials in env.

Usage:
    DATABASE_URL=... AWS_REGION=us-east-1 python3 scripts/load_bootstrap_transcripts.py \\
        --bootstrap-dir ../bootstrap [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest import ingest_source, make_source_id  # noqa: E402
from store import SourceInput  # noqa: E402
from embedding import EMBEDDING_MODEL  # noqa: E402

logger = logging.getLogger("load_bootstrap_transcripts")
logging.basicConfig(level=logging.INFO, format="%(message)s")


def load_sources(bootstrap_dir: Path) -> list[tuple[SourceInput, str]]:
    mapping_path = bootstrap_dir / "metadata" / "youtube_podcast_mapping.json"
    mapping = json.loads(mapping_path.read_text())["podcasts"]

    sources: list[tuple[SourceInput, str]] = []
    for meta in mapping.values():
        if not meta.get("has_local_transcript"):
            continue
        transcript_path = bootstrap_dir / "transcripts" / meta["transcript_file"]
        if not transcript_path.exists():
            logger.warning("missing transcript file, skipping: %s", transcript_path)
            continue

        source = SourceInput(
            source_id=make_source_id("youtube_caption", meta["youtube_id"]),
            source_type="youtube_caption",
            title=meta["youtube_title"],
            url=f"https://www.youtube.com/watch?v={meta['youtube_id']}",
            embedding_model=EMBEDDING_MODEL,
            doctors=meta.get("doctors", []),
            topics=meta.get("topics", []),
        )
        sources.append((source, transcript_path.read_text()))
    return sources


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap-dir", type=Path, default=Path(__file__).resolve().parent.parent.parent / "bootstrap")
    parser.add_argument("--dry-run", action="store_true", help="chunk + count only, no embedding calls or DB writes")
    args = parser.parse_args()

    sources = load_sources(args.bootstrap_dir)
    logger.info("found %d sources with local transcripts", len(sources))

    if args.dry_run:
        from chunking import chunk_text

        total_chunks = 0
        for source, text in sources:
            n = len(chunk_text(text))
            total_chunks += n
            logger.info("[dry-run] %s -> %d chunks", source.source_id, n)
        logger.info("[dry-run] total: %d sources, %d chunks (no embedding/DB calls made)", len(sources), total_chunks)
        return

    written = 0
    failed = 0
    for source, text in sources:
        result = ingest_source(source, text)
        if result.error:
            failed += 1
            logger.error("FAILED %s: %s", source.source_id, result.error)
        else:
            written += 1
            logger.info(
                "OK %s: %d chunks (%d written, %d skipped)",
                source.source_id,
                result.chunks_total,
                result.chunks_written,
                result.chunks_skipped,
            )

    logger.info("done: %d sources ingested, %d failed", written, failed)


if __name__ == "__main__":
    main()

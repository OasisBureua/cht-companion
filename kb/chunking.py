"""Chunk plain transcript/document text into embed-sized pieces (CHAT-20).

Character-based, target ~1024 chars (~256 tokens) with ~20% overlap, same
profile as the legacy chmbot's podcast chunker (see chatbot-inventory-2026-09-01.md
§5.3) but without the flat speaker-blob join that caused mid-turn boundary
splitting there — these sources carry no per-line speaker tags, so that
failure mode doesn't apply here; nothing to port.
"""

from __future__ import annotations

from dataclasses import dataclass

TARGET_CHARS = 1024
OVERLAP_CHARS = 205
_SEPARATORS = ("\n\n", "\n", ". ", " ")


@dataclass
class Chunk:
    index: int
    text: str


def _split_recursive(text: str, target_chars: int, seps: tuple[str, ...]) -> list[str]:
    """Split on the first separator that appears, then recurse into any
    resulting piece still over target_chars using the next, finer separator.
    Falls back to raw character slicing once separators are exhausted, so a
    single unbroken run of text (no punctuation, no newlines) still yields
    target_chars-sized pieces instead of one oversized piece.
    """
    if len(text) <= target_chars:
        return [text]

    for i, sep in enumerate(seps):
        if sep in text:
            parts = text.split(sep)
            joined = [p + sep if j < len(parts) - 1 else p for j, p in enumerate(parts)]
            remaining_seps = seps[i + 1 :]
            out: list[str] = []
            for piece in joined:
                out.extend(_split_recursive(piece, target_chars, remaining_seps) if len(piece) > target_chars else [piece])
            return out

    # no separator left and still oversized — hard character split
    return [text[i : i + target_chars] for i in range(0, len(text), target_chars)]


def chunk_text(text: str, *, target_chars: int = TARGET_CHARS, overlap_chars: int = OVERLAP_CHARS) -> list[Chunk]:
    """Recursive split: break on paragraph/line/sentence/word boundaries (in that
    order, recursing into any piece still over target_chars), then pack pieces
    into windows up to target_chars and step back overlap_chars between windows
    so context isn't lost at a boundary. Returns [] for blank input.
    """
    stripped = text.strip()
    if not stripped:
        return []

    pieces = _split_recursive(stripped, target_chars, _SEPARATORS)

    windows: list[str] = []
    current = ""
    for piece in pieces:
        if current and len(current) + len(piece) > target_chars:
            windows.append(current)
            # step back into the tail of the just-closed window for overlap
            tail = current[-overlap_chars:] if len(current) > overlap_chars else current
            current = tail + piece
        else:
            current += piece
    if current.strip():
        windows.append(current)

    return [Chunk(index=i, text=w.strip()) for i, w in enumerate(windows) if w.strip()]

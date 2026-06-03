"""Split plain text into overlapping windows with filing metadata.

Chunks snap to paragraph/sentence boundaries so they don't cut mid-sentence.
MiniLM-L6-v2 effective embedding window is ~256 tokens (≈960 chars).
CHUNK_SIZE is deliberately kept at 1500 chars so the bi-encoder captures the
opening paragraph of each section; the cross-encoder re-ranker compensates for
any retrieval imprecision by scoring the full chunk text at query time.
"""
from __future__ import annotations

from dataclasses import dataclass, field

CHUNK_SIZE = 1500    # chars; bi-encoder truncates to ~960 chars, re-ranker uses all
CHUNK_OVERLAP = 300  # increased from 200 — better cross-chunk continuity


@dataclass
class Chunk:
    text: str
    ticker: str
    form_type: str
    date: str
    accession_number: str
    source_url: str
    chunk_index: int
    extra: dict = field(default_factory=dict)


# Maximum chars to look back when snapping to a paragraph/sentence boundary.
# Must be < (CHUNK_SIZE - CHUNK_OVERLAP) to guarantee forward progress.
_SNAP_WINDOW = 250


def _snap_to_boundary(text: str, pos: int) -> int:
    """Return the nearest clean break at or before *pos*, within _SNAP_WINDOW chars.

    Prefers paragraph breaks, then sentence-ending periods, then line breaks.
    Falls back to the original position so callers never have to handle None.
    """
    start = max(0, pos - _SNAP_WINDOW)
    window = text[start:pos]
    for delim in ("\n\n", ".\n", ". ", "\n"):
        idx = window.rfind(delim)
        if idx >= 0:
            return start + idx + len(delim)
    return pos


def chunk_text(
    text: str,
    ticker: str,
    form_type: str,
    date: str,
    accession_number: str,
    source_url: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[Chunk]:
    """Split *text* into overlapping character windows, each tagged with filing metadata.

    Chunks end at the nearest paragraph/sentence boundary before the hard cut,
    preventing the chunker from splitting financial statements mid-sentence.
    """
    if overlap >= chunk_size:
        raise ValueError(f"overlap ({overlap}) must be less than chunk_size ({chunk_size})")
    chunks: list[Chunk] = []
    start = 0
    index = 0
    while start < len(text):
        raw_end = start + chunk_size
        # Snap to a clean boundary, but only if we're not already at the end
        if raw_end < len(text):
            end = _snap_to_boundary(text, raw_end)
        else:
            end = len(text)
        piece = text[start:end].strip()
        if piece:
            chunks.append(
                Chunk(
                    text=piece,
                    ticker=ticker,
                    form_type=form_type,
                    date=date,
                    accession_number=accession_number,
                    source_url=source_url,
                    chunk_index=index,
                )
            )
            index += 1
        # Stop after the last chunk rather than advancing 1 char at a time
        if end >= len(text):
            break
        step = (end - start) - overlap
        # Guard: always advance at least 1 char to prevent an infinite loop
        start += max(step, 1)
    return chunks

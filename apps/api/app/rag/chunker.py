"""Split plain text into overlapping windows with filing metadata."""
from __future__ import annotations

from dataclasses import dataclass, field

CHUNK_SIZE = 1500   # chars ≈ 375 tokens; fits all-MiniLM-L6-v2 (512-token max)
CHUNK_OVERLAP = 200


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
    """Split *text* into overlapping character windows, each tagged with filing metadata."""
    if overlap >= chunk_size:
        raise ValueError(f"overlap ({overlap}) must be less than chunk_size ({chunk_size})")
    chunks: list[Chunk] = []
    start = 0
    index = 0
    while start < len(text):
        end = start + chunk_size
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
        start += chunk_size - overlap
    return chunks

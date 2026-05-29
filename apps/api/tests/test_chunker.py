"""Unit tests for the text chunker — no external dependencies."""
from app.rag.chunker import CHUNK_OVERLAP, CHUNK_SIZE, Chunk, chunk_text


def _make_chunks(text: str, **kw) -> list[Chunk]:
    return chunk_text(
        text=text,
        ticker=kw.get("ticker", "AAPL"),
        form_type=kw.get("form_type", "8-K"),
        date=kw.get("date", "2025-01-01"),
        accession_number=kw.get("accession_number", "0000320193-25-000001"),
        source_url=kw.get("source_url", "https://example.com/filing.htm"),
    )


def test_short_text_produces_single_chunk() -> None:
    chunks = _make_chunks("Apple revenue was $100B.")
    assert len(chunks) == 1
    assert chunks[0].chunk_index == 0
    assert chunks[0].text == "Apple revenue was $100B."


def test_long_text_splits_into_multiple_chunks() -> None:
    text = "word " * 400  # 2000 chars > CHUNK_SIZE
    chunks = _make_chunks(text)
    assert len(chunks) > 1


def test_chunk_indices_are_sequential() -> None:
    text = "x" * (CHUNK_SIZE * 3)
    chunks = _make_chunks(text)
    for i, c in enumerate(chunks):
        assert c.chunk_index == i


def test_chunk_size_bounded() -> None:
    text = "a" * 10_000
    chunks = _make_chunks(text)
    for c in chunks:
        assert len(c.text) <= CHUNK_SIZE


def test_metadata_propagated() -> None:
    chunks = _make_chunks(
        "some text",
        ticker="GOOGL",
        form_type="10-Q",
        date="2024-10-31",
        accession_number="0001652044-24-000123",
        source_url="https://sec.gov/doc.htm",
    )
    c = chunks[0]
    assert c.ticker == "GOOGL"
    assert c.form_type == "10-Q"
    assert c.date == "2024-10-31"
    assert c.accession_number == "0001652044-24-000123"
    assert c.source_url == "https://sec.gov/doc.htm"


def test_overlap_ge_chunk_size_raises() -> None:
    import pytest
    with pytest.raises(ValueError, match="overlap"):
        chunk_text("some text", ticker="AAPL", form_type="8-K", date="2025-01-01",
                   accession_number="0000", source_url="https://x.com",
                   chunk_size=100, overlap=100)


def test_overlap_means_consecutive_chunks_share_content() -> None:
    # build text where each character position is unique-ish
    text = ("abcde" * 500)[:3000]  # 3000 chars → 3 chunks
    chunks = _make_chunks(text)
    if len(chunks) >= 2:
        # end of chunk 0 should appear at start of chunk 1
        tail = chunks[0].text[-(CHUNK_OVERLAP - 10):]
        assert tail in chunks[1].text

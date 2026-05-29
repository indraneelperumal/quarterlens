"""Integration tests for Phase 1 end-to-end flow.

These tests require live external services (EDGAR network + Qdrant) and are
automatically skipped when those services are unavailable.

Run after:
    docker compose up -d
    python -m scripts.ingest_watchlist AAPL
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.config import settings
from app.mcp import client as mcp_client

# Skip the entire module if the MCP server script is not present
_SERVER_SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "packages"
    / "mcp-servers"
    / "sec-edgar"
    / "server.py"
)
pytestmark = pytest.mark.skipif(
    not _SERVER_SCRIPT.exists(),
    reason="MCP server script not found",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def qdrant_store():
    """Return a live VectorStore, or skip if Qdrant is unreachable.

    Function-scoped so pytest.skip() only affects the one test that uses it,
    not the entire session (session-scoped fixtures raise Skipped globally).
    """
    from app.rag.store import VectorStore

    store = VectorStore(settings.qdrant_url)
    try:
        store._client.get_collections()
    except Exception as exc:
        pytest.skip(f"Qdrant not reachable: {exc}")
    return store


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_mcp_recent_filings_aapl() -> None:
    """MCP live call returns real AAPL 8-K filings from EDGAR."""
    import asyncio

    filings = await asyncio.wait_for(
        mcp_client.recent_filings("AAPL", "8-K", limit=10, user_agent=settings.sec_edgar_user_agent),
        timeout=60.0,
    )
    assert isinstance(filings, list), "Expected a list of filings"
    assert len(filings) > 0, "Expected at least one 8-K filing for AAPL"
    first = filings[0]
    assert "date" in first, "Filing missing 'date'"
    assert "accession_number" in first, "Filing missing 'accession_number'"
    assert "form" in first, "Filing missing 'form'"
    assert first["form"] == "8-K", f"Expected 8-K, got {first['form']}"


async def test_qdrant_search_aapl_8k(qdrant_store) -> None:
    """Semantic search returns AAPL 8-K chunks (requires prior ingest run)."""
    from app.rag.embedder import embed_texts

    try:
        count = qdrant_store.count()
    except Exception:
        pytest.skip("financial_docs collection not found — run ingest_watchlist.py first")
    if count == 0:
        pytest.skip("Qdrant collection is empty — run ingest_watchlist.py first")

    vec = embed_texts(["Apple 8-K material event disclosure"])[0]
    results = qdrant_store.search(vec, limit=5, ticker="AAPL")

    assert isinstance(results, list), "Expected a list from Qdrant search"
    assert len(results) > 0, "No results — did you run ingest_watchlist.py AAPL?"

    top = results[0]
    assert "text" in top, "Result missing 'text'"
    assert "date" in top, "Result missing 'date'"
    assert "score" in top, "Result missing 'score'"
    assert top["ticker"] == "AAPL", f"Expected ticker AAPL, got {top['ticker']}"
    assert 0.0 <= top["score"] <= 1.0, f"Score out of range: {top['score']}"

"""Fetch SEC filings, chunk, embed, and upsert to Qdrant."""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# Reach across the monorepo to import EdgarClient without packaging it separately
_EDGAR_PKG = Path(__file__).resolve().parents[4] / "packages" / "mcp-servers" / "sec-edgar"
sys.path.insert(0, str(_EDGAR_PKG))

from edgar_client import EdgarClient  # noqa: E402

from app.rag.chunker import chunk_text
from app.rag.embedder import embed_texts
from app.rag.store import VectorStore

log = logging.getLogger(__name__)

# How many filings of each type to ingest per ticker
_FORMS: dict[str, int] = {
    "8-K": 5,
    "10-Q": 3,
    "10-K": 1,
}


async def ingest_ticker(
    ticker: str,
    store: VectorStore,
    user_agent: str,
) -> dict[str, int]:
    """Fetch, chunk, embed, and store all configured form types for *ticker*.

    Returns a mapping of ``form/accession → chunks_written``.
    """
    ticker = ticker.upper()
    totals: dict[str, int] = {}

    async with EdgarClient(user_agent) as client:
        for form_type, limit in _FORMS.items():
            try:
                filings = await client.get_recent_filings(ticker, form_type, limit)
            except Exception as exc:
                log.warning("get_recent_filings(%s, %s) failed: %s", ticker, form_type, exc)
                continue

            for filing in filings:
                acc = filing["accession_number"]
                cik = filing["cik"]
                try:
                    docs = await client.get_filing_documents(cik, acc)
                    url = docs["exhibit_url"] or docs["primary_url"]
                    if not url:
                        log.debug("No document URL for %s %s", ticker, acc)
                        continue
                    text = await client.get_filing_content(url, max_chars=20_000)
                except Exception as exc:
                    log.warning("Content fetch failed %s %s: %s", ticker, acc, exc)
                    continue

                chunks = chunk_text(
                    text=text,
                    ticker=ticker,
                    form_type=form_type,
                    date=filing["date"],
                    accession_number=acc,
                    source_url=url,
                )
                if not chunks:
                    continue

                embeddings = embed_texts([c.text for c in chunks])
                n = store.upsert(chunks, embeddings)
                totals[f"{form_type}/{acc}"] = n
                log.info("  %s %s %s → %d chunks", ticker, form_type, acc, n)

    return totals


async def ingest_tickers(
    tickers: list[str],
    qdrant_url: str,
    user_agent: str,
) -> None:
    """Ensure the Qdrant collection exists, then ingest each ticker sequentially."""
    store = VectorStore(qdrant_url)
    store.ensure_collection()

    for ticker in tickers:
        log.info("Ingesting %s …", ticker)
        result = await ingest_ticker(ticker, store, user_agent)
        total_chunks = sum(result.values())
        log.info("%s complete — %d total chunks across %d filings", ticker, total_chunks, len(result))

"""Anthropic tool definitions and async executors for the agent loop.

Tool call cost order (cheapest → most expensive):
  1. search_docs          — local Qdrant vector DB, no network, no API cost
  2. get_stock_quote      — single FMP API call
  3. get_earnings_history — single FMP API call
  4. get_news_sentiment   — single Alpha Vantage call
  5. search_news          — Tavily search API call
  6. search_sec_filings   — live EDGAR network call (metadata only)
  7. get_filing_content   — live EDGAR full-text fetch (most expensive)

The tool descriptions below encode this priority so the model routes correctly.
"""
from __future__ import annotations

import asyncio
import json
from functools import partial
from typing import Any

from app.agent.schema import Citation
from app.mcp import client as mcp_client
from app.mcp import market_client, news
from app.rag.embedder import embed_texts, rerank
from app.rag.store import VectorStore

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "search_docs",
        "description": (
            "ALWAYS call this first for any question about SEC filings, earnings disclosures, "
            "management commentary, risk factors, or historical financial statements. "
            "Searches a local vector database of already-ingested 10-K, 10-Q, and 8-K chunks — "
            "instant, no API cost, no network call. "
            "Only fall back to search_sec_filings if this returns no relevant results "
            "OR the user explicitly asks for the most recent filing from the last 30 days."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural-language question or topic, e.g. 'Apple Q2 2026 revenue guidance'"},
                "ticker": {"type": "string", "description": "Limit results to this ticker (optional but recommended when known)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_stock_quote",
        "description": (
            "Get the live stock quote for a ticker: current price, daily change %, "
            "market cap, 52-week high/low. "
            "Use for: 'what is X trading at', 'stock price', 'market cap'. "
            "Do NOT use for historical prices or EPS data."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker, e.g. 'AAPL'"},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_earnings_history",
        "description": (
            "Return historical EPS actuals vs estimates and surprise % for the last N quarters. "
            "Use for: 'EPS history', 'earnings beats/misses', 'did X beat estimates'. "
            "Do NOT use search_docs for EPS numbers — this endpoint is more accurate."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker, e.g. 'AAPL'"},
                "limit": {"type": "integer", "description": "Number of quarters (1–5, default 4)", "default": 4},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "search_news",
        "description": (
            "Search for recent news articles using a free-text query. "
            "Use ONLY when the user asks about recent events, headlines, or news from the past few days "
            "that would not be in SEC filings. "
            "Do NOT use for historical filing content — use search_docs instead."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query, e.g. 'Apple AI partnership announcement June 2026'"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_news_sentiment",
        "description": (
            "Get bullish/bearish/neutral sentiment scores for a ticker from news articles. "
            "Use ONLY when the user explicitly asks about market sentiment, "
            "analyst mood, or overall perception — not for factual financial data."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker, e.g. 'AAPL'"},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "search_sec_filings",
        "description": (
            "Search LIVE SEC EDGAR for filing metadata (accession numbers, dates, descriptions). "
            "Returns metadata ONLY — no filing content. "
            "Use ONLY when: (1) search_docs returned no relevant results, "
            "(2) the user needs a filing filed in the last 30 days not yet in the local DB, "
            "or (3) the user explicitly asks 'what is the latest 8-K'. "
            "Then call get_filing_content to read the actual text."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker, e.g. 'AAPL'"},
                "form_type": {"type": "string", "description": "SEC form type: '8-K', '10-Q', '10-K'", "default": "8-K"},
                "limit": {"type": "integer", "description": "Max results (1–10)", "default": 5},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_filing_content",
        "description": (
            "Fetch full text of a specific SEC filing by accession number. "
            "EXPENSIVE and slow — makes a live network call to EDGAR. "
            "Use ONLY when you have an accession_number from search_sec_filings "
            "AND search_docs did not already answer the question. "
            "Prefer search_docs whenever possible."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker, e.g. 'AAPL'"},
                "accession_number": {"type": "string", "description": "SEC accession number, e.g. '0000320193-26-000052'"},
                "max_chars": {"type": "integer", "description": "Max characters to return (default 3000)", "default": 3000},
            },
            "required": ["ticker", "accession_number"],
        },
    },
]


def extract_citations(tool_name: str, result: Any) -> list[Citation]:
    """Extract Citation objects from a tool result, if applicable."""
    if isinstance(result, Exception) or not isinstance(result, list):
        return []
    citations: list[Citation] = []
    if tool_name == "search_sec_filings":
        for f in result:
            if not isinstance(f, dict) or not f.get("accession_number"):
                continue
            citations.append(Citation(
                accession_number=f.get("accession_number", ""),
                date=f.get("date", ""),
                form_type=f.get("form_type") or f.get("form", "8-K"),
            ))
    elif tool_name == "search_docs":
        for c in result:
            if not isinstance(c, dict) or not c.get("accession_number"):
                continue
            raw_text = c.get("text", "")
            citations.append(Citation(
                accession_number=c.get("accession_number", ""),
                date=c.get("date", ""),
                form_type=c.get("form_type", ""),
                excerpt=raw_text[:150] if raw_text else None,
                source_url=c.get("source_url", ""),
            ))
    return citations


def safe_json(result: Any) -> str:
    """Serialize a tool result to a JSON string for the Anthropic tool_result content field.

    Called by the agent loop on each execute_tool() return value (including
    Exception objects captured via asyncio.gather(..., return_exceptions=True)).
    """
    if isinstance(result, Exception):
        return json.dumps({"error": str(result)})
    return json.dumps(result, default=str)


def _qdrant_search(vector: list[float], ticker: str | None) -> list[dict]:
    from app.config import settings
    store = VectorStore(settings.qdrant_url, settings.qdrant_api_key)
    store.ensure_collection()
    # Fetch 20 candidates; the cross-encoder reranker narrows these to top 5
    return store.search(vector, limit=20, ticker=ticker)


async def execute_tool(block: Any, ticker: str | None, settings: Any) -> Any:
    """Execute a single tool_use block and return the raw result."""
    name = block.name
    inp: dict[str, Any] = block.input

    if name == "search_sec_filings":
        return await mcp_client.recent_filings(
            inp["ticker"],
            inp.get("form_type", "8-K"),
            limit=inp.get("limit", 5),
            user_agent=settings.sec_edgar_user_agent,
        )

    if name == "get_filing_content":
        return await mcp_client.filing_content(
            inp["ticker"],
            inp["accession_number"],
            max_chars=inp.get("max_chars", 8000),
            user_agent=settings.sec_edgar_user_agent,
        )

    if name == "get_stock_quote":
        if not settings.fmp_api_key:
            return {"error": "FMP_API_KEY not configured"}
        return await market_client.get_quote(inp["ticker"], api_key=settings.fmp_api_key)

    if name == "get_earnings_history":
        if not settings.fmp_api_key:
            return {"error": "FMP_API_KEY not configured"}
        return await market_client.get_earnings_history(
            inp["ticker"], limit=inp.get("limit", 4), api_key=settings.fmp_api_key
        )

    if name == "search_news":
        if not settings.tavily_api_key:
            return []
        return await news.search_news(inp["query"], api_key=settings.tavily_api_key)

    if name == "get_news_sentiment":
        if not settings.alpha_vantage_api_key:
            return {"ticker": inp["ticker"], "articles": [], "count": 0}
        return await news.get_news_sentiment(
            inp["ticker"], api_key=settings.alpha_vantage_api_key
        )

    if name == "search_docs":
        loop = asyncio.get_running_loop()
        query = inp["query"]
        vec = await loop.run_in_executor(None, partial(embed_texts, [query]))
        docs = await loop.run_in_executor(
            None, partial(_qdrant_search, vec[0], inp.get("ticker") or ticker)
        )
        # Re-rank: bi-encoder fetches 20 candidates, cross-encoder keeps top 5.
        # Runs in executor to keep the async loop unblocked.
        if len(docs) > 1:
            docs = await loop.run_in_executor(None, partial(rerank, query, docs, 5))
        return docs

    raise ValueError(f"Unknown tool: {name!r}")

"""Anthropic tool definitions and async executors for the agent loop."""
from __future__ import annotations

import asyncio
import json
from functools import partial
from typing import Any

from app.agent.schema import Citation
from app.mcp import client as mcp_client
from app.mcp import market_client, news
from app.rag.embedder import embed_texts
from app.rag.store import VectorStore

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "search_sec_filings",
        "description": (
            "Search SEC EDGAR for recent filings for a stock ticker. "
            "Returns a list of filing metadata (accession number, date, description)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker, e.g. 'AAPL'"},
                "form_type": {"type": "string", "description": "SEC form type, e.g. '8-K', '10-Q'", "default": "8-K"},
                "limit": {"type": "integer", "description": "Max results to return (1-10)", "default": 5},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_filing_content",
        "description": (
            "Fetch the full text of a specific SEC filing by accession number. "
            "Returns cleaned plain text of the filing, truncated to max_chars."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker, e.g. 'AAPL'"},
                "accession_number": {"type": "string", "description": "SEC accession number, e.g. '0000320193-26-000052'"},
                "max_chars": {"type": "integer", "description": "Max characters to return", "default": 8000},
            },
            "required": ["ticker", "accession_number"],
        },
    },
    {
        "name": "get_stock_quote",
        "description": (
            "Get the current stock quote for a ticker: price, daily change, "
            "market cap, 52-week range."
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
            "Return historical EPS actuals vs estimates for a stock, including "
            "surprise percentage for each quarter."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker, e.g. 'AAPL'"},
                "limit": {"type": "integer", "description": "Number of quarters to return (1-5)", "default": 4},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "search_news",
        "description": (
            "Search for recent financial news articles using a query string. "
            "Returns titles, sources, snippets, and published dates."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query, e.g. 'Apple earnings Q2 2026'"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_news_sentiment",
        "description": (
            "Get news sentiment scores for a stock ticker from Alpha Vantage. "
            "Returns bullish/bearish/neutral labels and scores for recent articles."
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
        "name": "search_docs",
        "description": (
            "Semantic search over ingested SEC filing chunks stored in the vector DB. "
            "Returns the most relevant text passages for the query."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural-language question or topic to search for"},
                "ticker": {"type": "string", "description": "Filter results to this ticker (optional)"},
            },
            "required": ["query"],
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
    store = VectorStore(settings.qdrant_url)
    store.ensure_collection()
    # No form_type filter: search_docs covers all ingested filing types
    return store.search(vector, limit=5, ticker=ticker)


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
        vec = await loop.run_in_executor(None, partial(embed_texts, [inp["query"]]))
        return await loop.run_in_executor(
            None, partial(_qdrant_search, vec[0], inp.get("ticker") or ticker)
        )

    raise ValueError(f"Unknown tool: {name!r}")

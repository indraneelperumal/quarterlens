"""
Market data MCP server.

Exposes Financial Modeling Prep (FMP) tools for live market context:
  - get_quote              : current quote and daily performance
  - get_earnings_history   : historical EPS actuals vs estimates
  - get_earnings_calendar  : upcoming earnings between two dates
  - get_key_metrics_ttm    : trailing-12-month key metrics

Run:
    python server.py          (stdio transport - default for MCP clients)
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date as _date
import json
import os
import re
from typing import Any, AsyncIterator, Awaitable, Callable, TypeVar

from mcp.server.fastmcp import FastMCP

from fmp_client import FMPClient

# ---------------------------------------------------------------------------
# Server setup
# ---------------------------------------------------------------------------

_API_KEY = os.getenv("FMP_API_KEY", "")
_client: FMPClient | None = FMPClient(_API_KEY) if _API_KEY else None

_T = TypeVar("_T")
_TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.-]{0,14}$")
_MAX_CALENDAR_DAYS = 366


@asynccontextmanager
async def _lifespan(_: FastMCP) -> AsyncIterator[dict[str, Any]]:
    try:
        yield {}
    finally:
        if _client is not None:
            await _client.close()


mcp = FastMCP("market-data", lifespan=_lifespan)


def _normalize_ticker(ticker: str) -> str:
    normalized = ticker.upper().strip()
    if not normalized:
        raise ValueError("ticker is required")
    if not _TICKER_RE.fullmatch(normalized):
        raise ValueError(f"invalid ticker: {ticker!r}")
    return normalized


def _validate_date_range(from_date: str, to_date: str) -> None:
    start = _date.fromisoformat(from_date)
    end = _date.fromisoformat(to_date)
    if start > end:
        raise ValueError("from_date must be on or before to_date")
    if (end - start).days > _MAX_CALENDAR_DAYS:
        raise ValueError(f"date range cannot exceed {_MAX_CALENDAR_DAYS} days")


async def _call_fmp(action: Callable[[FMPClient], Awaitable[_T]]) -> str:
    """Run an FMP call and return MCP-friendly text."""
    if _client is None:
        return "ERROR: FMP_API_KEY not set"

    try:
        data = await action(_client)
    except Exception as exc:
        return f"ERROR: {exc}"

    return json.dumps(data)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_quote(ticker: str) -> str:
    """
    Return the latest quote and daily performance for a stock ticker.

    Args:
        ticker: Stock ticker, e.g. 'AAPL', 'NVDA', 'GOOGL'.

    Returns:
        JSON object from FMP, or null if FMP has no quote for the ticker.
        Returns an error string prefixed with 'ERROR:' on failure.
    """
    try:
        ticker = _normalize_ticker(ticker)
    except ValueError as exc:
        return f"ERROR: {exc}"

    return await _call_fmp(lambda client: client.get_quote(ticker))


@mcp.tool()
async def get_earnings_history(ticker: str, limit: int = 4) -> str:
    """
    Return historical EPS actuals vs estimates for a stock ticker.

    Args:
        ticker: Stock ticker, e.g. 'AAPL'.
        limit : Maximum number of records to return. Clamped to 1-12, but the
                free-tier FMP API delivers at most 5 historical quarters.

    Returns:
        JSON array of earnings records. Each record includes surprisePct when
        actual and estimated EPS are available.
        Returns an error string prefixed with 'ERROR:' on failure.
    """
    try:
        ticker = _normalize_ticker(ticker)
    except ValueError as exc:
        return f"ERROR: {exc}"

    limit = max(1, min(limit, 12))
    return await _call_fmp(
        lambda client: client.get_earnings_history(ticker, limit=limit)
    )


@mcp.tool()
async def get_earnings_calendar(from_date: str, to_date: str) -> str:
    """
    Return upcoming earnings announcements between two dates.

    Args:
        from_date: Start date in YYYY-MM-DD format.
        to_date  : End date in YYYY-MM-DD format.

    Returns:
        JSON array of earnings calendar records.
        Returns an error string prefixed with 'ERROR:' on failure.
    """
    try:
        _validate_date_range(from_date, to_date)
    except ValueError as exc:
        return f"ERROR: {exc}"

    return await _call_fmp(
        lambda client: client.get_earnings_calendar(from_date, to_date)
    )


@mcp.tool()
async def get_key_metrics_ttm(ticker: str) -> str:
    """
    Return trailing-12-month key financial metrics for a stock ticker.

    Args:
        ticker: Stock ticker, e.g. 'AAPL'.

    Returns:
        JSON object from FMP, or null if FMP has no metrics for the ticker.
        Returns an error string prefixed with 'ERROR:' on failure.
    """
    try:
        ticker = _normalize_ticker(ticker)
    except ValueError as exc:
        return f"ERROR: {exc}"

    return await _call_fmp(lambda client: client.get_key_metrics_ttm(ticker))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()

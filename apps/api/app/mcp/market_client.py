"""Stdio MCP client for the market-data server.

Spawns `packages/mcp-servers/market-data/server.py` as a child process,
initializes the MCP session, and exposes one-shot tool calls.

Phase 3 will replace the per-call spawn with a persistent session pool.
"""
from __future__ import annotations

import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Absolute path to the MCP server script (monorepo-relative)
_SERVER_SCRIPT = (
    Path(__file__).resolve().parents[4]
    / "packages"
    / "mcp-servers"
    / "market-data"
    / "server.py"
)


@asynccontextmanager
async def _market_session(api_key: str) -> AsyncIterator[ClientSession]:
    """Yield a live MCP ClientSession connected to the market-data server."""
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(_SERVER_SCRIPT)],
        env={**os.environ, "FMP_API_KEY": api_key},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


async def market_tool(
    tool_name: str,
    args: dict[str, Any],
    api_key: str,
) -> str:
    """Call one market-data MCP tool and return its text response."""
    async with _market_session(api_key) as session:
        result = await session.call_tool(tool_name, args)
    if result.isError:
        detail = result.content[0].text if result.content else repr(result.content)
        raise RuntimeError(f"MCP tool error from {tool_name!r}: {detail}")
    if not result.content:
        return ""
    text = result.content[0].text
    if text.startswith("ERROR:"):
        raise RuntimeError(f"{tool_name!r} returned: {text}")
    return text


async def get_quote(ticker: str, api_key: str) -> dict[str, Any] | None:
    """Return latest quote data for *ticker* via the market-data MCP server."""
    raw = await market_tool("get_quote", {"ticker": ticker}, api_key)
    return json.loads(raw)


async def get_earnings_history(
    ticker: str,
    limit: int = 4,
    api_key: str = "",
) -> list[dict[str, Any]]:
    """Return EPS actuals vs estimates for *ticker* via the MCP server."""
    raw = await market_tool(
        "get_earnings_history",
        {"ticker": ticker, "limit": limit},
        api_key,
    )
    return json.loads(raw)


async def get_earnings_calendar(
    from_date: str,
    to_date: str,
    api_key: str,
) -> list[dict[str, Any]]:
    """Return earnings calendar entries between *from_date* and *to_date*."""
    raw = await market_tool(
        "get_earnings_calendar",
        {"from_date": from_date, "to_date": to_date},
        api_key,
    )
    return json.loads(raw)


async def get_key_metrics_ttm(ticker: str, api_key: str) -> dict[str, Any] | None:
    """Return trailing-12-month key metrics for *ticker* via the MCP server."""
    raw = await market_tool("get_key_metrics_ttm", {"ticker": ticker}, api_key)
    return json.loads(raw)

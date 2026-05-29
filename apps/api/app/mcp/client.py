"""Stdio MCP client for the SEC EDGAR server.

Spawns `packages/mcp-servers/sec-edgar/server.py` as a child process,
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
    / "sec-edgar"
    / "server.py"
)


@asynccontextmanager
async def _sec_session(user_agent: str) -> AsyncIterator[ClientSession]:
    """Yield a live MCP ClientSession connected to the SEC EDGAR server."""
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(_SERVER_SCRIPT)],
        env={**os.environ, "SEC_EDGAR_USER_AGENT": user_agent},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


async def sec_tool(
    tool_name: str,
    args: dict[str, Any],
    user_agent: str,
) -> str:
    """Call one SEC EDGAR MCP tool and return its text response.

    Spawns the server process, calls the tool, then tears down.
    Suitable for infrequent / on-demand tool calls in Phase 1–2.
    """
    async with _sec_session(user_agent) as session:
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


async def resolve_ticker(ticker: str, user_agent: str) -> dict[str, str]:
    """Return ``{ticker, cik}`` for *ticker* via the MCP server."""
    raw = await sec_tool("resolve_ticker_to_cik", {"ticker": ticker}, user_agent)
    return json.loads(raw)


async def recent_filings(
    ticker: str,
    form_type: str = "8-K",
    limit: int = 5,
    user_agent: str = "",
) -> list[dict]:
    """Return recent filings list via the MCP server."""
    raw = await sec_tool(
        "get_recent_filings",
        {"ticker": ticker, "form_type": form_type, "limit": limit},
        user_agent,
    )
    return json.loads(raw)


async def filing_content(
    ticker: str,
    accession_number: str,
    max_chars: int = 8000,
    user_agent: str = "",
) -> str:
    """Return cleaned filing text via the MCP server."""
    return await sec_tool(
        "get_filing_content",
        {"ticker": ticker, "accession_number": accession_number, "max_chars": max_chars},
        user_agent,
    )

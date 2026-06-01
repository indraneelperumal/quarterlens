from __future__ import annotations

from contextlib import asynccontextmanager
import sys

import pytest

from app.mcp import market_client


async def test_get_quote_parses_json(monkeypatch) -> None:
    calls: list[tuple[str, dict, str]] = []

    async def fake_market_tool(tool_name: str, args: dict, api_key: str) -> str:
        calls.append((tool_name, args, api_key))
        return '{"symbol":"AAPL","price":123.45}'

    monkeypatch.setattr(market_client, "market_tool", fake_market_tool)

    result = await market_client.get_quote("AAPL", api_key="test-key")

    assert result == {"symbol": "AAPL", "price": 123.45}
    assert calls == [("get_quote", {"ticker": "AAPL"}, "test-key")]


async def test_get_earnings_history_parses_json_and_passes_limit(monkeypatch) -> None:
    calls: list[tuple[str, dict, str]] = []

    async def fake_market_tool(tool_name: str, args: dict, api_key: str) -> str:
        calls.append((tool_name, args, api_key))
        return '[{"symbol":"NVDA","surprisePct":8.5}]'

    monkeypatch.setattr(market_client, "market_tool", fake_market_tool)

    result = await market_client.get_earnings_history("NVDA", limit=6, api_key="test-key")

    assert result == [{"symbol": "NVDA", "surprisePct": 8.5}]
    assert calls == [
        ("get_earnings_history", {"ticker": "NVDA", "limit": 6}, "test-key")
    ]


async def test_get_earnings_calendar_parses_json(monkeypatch) -> None:
    calls: list[tuple[str, dict, str]] = []

    async def fake_market_tool(tool_name: str, args: dict, api_key: str) -> str:
        calls.append((tool_name, args, api_key))
        return '[{"symbol":"MSFT","date":"2026-01-30"}]'

    monkeypatch.setattr(market_client, "market_tool", fake_market_tool)

    result = await market_client.get_earnings_calendar(
        "2026-01-01",
        "2026-01-31",
        api_key="test-key",
    )

    assert result == [{"symbol": "MSFT", "date": "2026-01-30"}]
    assert calls == [
        (
            "get_earnings_calendar",
            {"from_date": "2026-01-01", "to_date": "2026-01-31"},
            "test-key",
        )
    ]


async def test_get_key_metrics_ttm_parses_json(monkeypatch) -> None:
    calls: list[tuple[str, dict, str]] = []

    async def fake_market_tool(tool_name: str, args: dict, api_key: str) -> str:
        calls.append((tool_name, args, api_key))
        return '{"symbol":"COST","peRatioTTM":52.1}'

    monkeypatch.setattr(market_client, "market_tool", fake_market_tool)

    result = await market_client.get_key_metrics_ttm("COST", api_key="test-key")

    assert result == {"symbol": "COST", "peRatioTTM": 52.1}
    assert calls == [("get_key_metrics_ttm", {"ticker": "COST"}, "test-key")]


async def test_market_tool_raises_on_tool_error(monkeypatch) -> None:
    class FakeContent:
        text = "transport failed"

    class FakeResult:
        isError = True
        content = [FakeContent()]

    class FakeSession:
        async def call_tool(self, tool_name: str, args: dict) -> FakeResult:
            return FakeResult()

    @asynccontextmanager
    async def fake_market_session(api_key: str):
        yield FakeSession()

    monkeypatch.setattr(market_client, "_market_session", fake_market_session)

    with pytest.raises(RuntimeError, match="MCP tool error"):
        await market_client.market_tool("get_quote", {"ticker": "AAPL"}, "test-key")


async def test_market_tool_raises_on_error_text(monkeypatch) -> None:
    class FakeContent:
        text = "ERROR: FMP_API_KEY not set"

    class FakeResult:
        isError = False
        content = [FakeContent()]

    class FakeSession:
        async def call_tool(self, tool_name: str, args: dict) -> FakeResult:
            return FakeResult()

    @asynccontextmanager
    async def fake_market_session(api_key: str):
        yield FakeSession()

    monkeypatch.setattr(market_client, "_market_session", fake_market_session)

    with pytest.raises(RuntimeError, match="get_quote"):
        await market_client.market_tool("get_quote", {"ticker": "AAPL"}, "test-key")


async def test_market_tool_returns_empty_string_for_empty_content(monkeypatch) -> None:
    class FakeResult:
        isError = False
        content = []

    class FakeSession:
        async def call_tool(self, tool_name: str, args: dict) -> FakeResult:
            return FakeResult()

    @asynccontextmanager
    async def fake_market_session(api_key: str):
        yield FakeSession()

    monkeypatch.setattr(market_client, "_market_session", fake_market_session)

    assert await market_client.market_tool("get_quote", {"ticker": "AAPL"}, "test-key") == ""


async def test_market_session_builds_stdio_params_and_initializes(monkeypatch) -> None:
    captured: dict = {}

    @asynccontextmanager
    async def fake_stdio_client(params):
        captured["params"] = params
        yield "read-stream", "write-stream"

    class FakeClientSession:
        def __init__(self, read, write) -> None:
            captured["read"] = read
            captured["write"] = write
            self.initialized = False

        async def __aenter__(self):
            captured["session"] = self
            return self

        async def __aexit__(self, *_: object) -> None:
            captured["closed"] = True

        async def initialize(self) -> None:
            self.initialized = True

    monkeypatch.setattr(market_client, "stdio_client", fake_stdio_client)
    monkeypatch.setattr(market_client, "ClientSession", FakeClientSession)

    async with market_client._market_session("test-key") as session:
        assert session.initialized is True

    params = captured["params"]
    assert params.command == sys.executable
    assert params.args == [str(market_client._SERVER_SCRIPT)]
    assert params.env["FMP_API_KEY"] == "test-key"
    assert market_client._SERVER_SCRIPT.name == "server.py"
    assert market_client._SERVER_SCRIPT.parent.name == "market-data"
    assert captured["read"] == "read-stream"
    assert captured["write"] == "write-stream"
    assert captured["closed"] is True

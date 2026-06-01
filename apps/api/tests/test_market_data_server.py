from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_MARKET_DATA_PATH = (
    Path(__file__).resolve().parents[3] / "packages" / "mcp-servers" / "market-data"
)
sys.path.insert(0, str(_MARKET_DATA_PATH))

_SERVER_PATH = _MARKET_DATA_PATH / "server.py"
_SPEC = importlib.util.spec_from_file_location("market_data_mcp_server", _SERVER_PATH)
assert _SPEC is not None
assert _SPEC.loader is not None
server = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = server
_SPEC.loader.exec_module(server)


class FakeFMPClient:
    async def get_quote(self, ticker: str):
        return {"symbol": ticker, "price": 123.45}

    async def get_earnings_history(self, ticker: str, limit: int = 4):
        return [{"symbol": ticker, "limit": limit}]

    async def get_earnings_calendar(self, from_date: str, to_date: str):
        return [{"from": from_date, "to": to_date}]

    async def get_key_metrics_ttm(self, ticker: str):
        return {"symbol": ticker, "peRatioTTM": 25.1}


@pytest.fixture(autouse=True)
def reset_client(monkeypatch):
    monkeypatch.setattr(server, "_client", None)


async def test_missing_api_key_returns_error() -> None:
    assert await server.get_quote("AAPL") == "ERROR: FMP_API_KEY not set"


async def test_empty_ticker_returns_error() -> None:
    assert await server.get_quote(" ") == "ERROR: ticker is required"


async def test_invalid_ticker_returns_error() -> None:
    result = await server.get_quote("AAPL/../../bad")

    assert result.startswith("ERROR: invalid ticker:")


async def test_quote_returns_json_and_normalizes_ticker(monkeypatch) -> None:
    monkeypatch.setattr(server, "_client", FakeFMPClient())

    result = await server.get_quote(" aapl ")

    assert json.loads(result) == {"symbol": "AAPL", "price": 123.45}


async def test_earnings_history_clamps_limit(monkeypatch) -> None:
    monkeypatch.setattr(server, "_client", FakeFMPClient())

    result = await server.get_earnings_history("NVDA", limit=99)

    assert json.loads(result) == [{"symbol": "NVDA", "limit": 12}]


async def test_earnings_calendar_rejects_reversed_dates() -> None:
    result = await server.get_earnings_calendar("2026-02-01", "2026-01-01")

    assert result == "ERROR: from_date must be on or before to_date"


async def test_earnings_calendar_returns_json(monkeypatch) -> None:
    monkeypatch.setattr(server, "_client", FakeFMPClient())

    result = await server.get_earnings_calendar("2026-01-01", "2026-01-31")

    assert json.loads(result) == [{"from": "2026-01-01", "to": "2026-01-31"}]


async def test_key_metrics_returns_json(monkeypatch) -> None:
    monkeypatch.setattr(server, "_client", FakeFMPClient())

    result = await server.get_key_metrics_ttm("msft")

    assert json.loads(result) == {"symbol": "MSFT", "peRatioTTM": 25.1}

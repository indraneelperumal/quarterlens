"""Tests for the /market REST endpoints."""
from fastapi.testclient import TestClient

from app.main import app
from app.routes import market as market_route

client = TestClient(app)


def test_quote_returns_data(monkeypatch) -> None:
    async def fake_get_quote(ticker: str, api_key: str):
        return {"symbol": ticker, "price": 185.23, "marketCap": 2_800_000_000_000}

    monkeypatch.setattr(market_route.market_client, "get_quote", fake_get_quote)
    monkeypatch.setattr(market_route.settings, "fmp_api_key", "test-key")

    response = client.get("/market/quote/AAPL")
    assert response.status_code == 200
    data = response.json()
    assert data["price"] == 185.23
    assert "marketCap" in data


def test_quote_no_key_returns_empty(monkeypatch) -> None:
    monkeypatch.setattr(market_route.settings, "fmp_api_key", "")

    response = client.get("/market/quote/AAPL")
    assert response.status_code == 200
    assert response.json() == {}


def test_earnings_returns_list(monkeypatch) -> None:
    async def fake_get_earnings_history(ticker: str, limit: int = 4, api_key: str = ""):
        return [
            {"date": "2026-01-30", "eps": 2.40, "epsEstimated": 2.35, "surprisePct": 2.13},
            {"date": "2025-10-31", "eps": 1.64, "epsEstimated": 1.60, "surprisePct": 2.50},
        ]

    monkeypatch.setattr(market_route.market_client, "get_earnings_history", fake_get_earnings_history)
    monkeypatch.setattr(market_route.settings, "fmp_api_key", "test-key")

    response = client.get("/market/earnings/AAPL")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 2
    assert "eps" in data[0]
    assert "date" in data[0]


def test_calendar_returns_list(monkeypatch) -> None:
    async def fake_get_earnings_calendar(from_date: str, to_date: str, api_key: str):
        return [
            {"symbol": "AAPL", "date": "2026-06-10", "epsEstimated": 1.45, "time": "amc"},
            {"symbol": "NVDA", "date": "2026-06-12", "epsEstimated": 0.89, "time": "amc"},
        ]

    monkeypatch.setattr(market_route.market_client, "get_earnings_calendar", fake_get_earnings_calendar)
    monkeypatch.setattr(market_route.settings, "fmp_api_key", "test-key")

    response = client.get("/market/calendar")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert data[0]["symbol"] == "AAPL"


def test_metrics_returns_data(monkeypatch) -> None:
    async def fake_get_key_metrics_ttm(ticker: str, api_key: str):
        return {"peRatioTTM": 31.2, "pbRatioTTM": 8.1, "roeTTM": 1.42, "debtToEquityTTM": 1.5}

    monkeypatch.setattr(market_route.market_client, "get_key_metrics_ttm", fake_get_key_metrics_ttm)
    monkeypatch.setattr(market_route.settings, "fmp_api_key", "test-key")

    response = client.get("/market/metrics/AAPL")
    assert response.status_code == 200
    data = response.json()
    assert "peRatioTTM" in data
    assert data["peRatioTTM"] == 31.2


def test_quote_lowercase_ticker_normalised(monkeypatch) -> None:
    received: list[str] = []

    async def fake_get_quote(ticker: str, api_key: str):
        received.append(ticker)
        return {"symbol": ticker, "price": 185.0}

    monkeypatch.setattr(market_route.market_client, "get_quote", fake_get_quote)
    monkeypatch.setattr(market_route.settings, "fmp_api_key", "test-key")

    client.get("/market/quote/aapl")
    assert received == ["AAPL"], "Ticker must be uppercased before calling market_client"


def test_metrics_none_return_becomes_empty(monkeypatch) -> None:
    async def fake_get_key_metrics_ttm(ticker: str, api_key: str):
        return None  # FMP returns None for unknown tickers

    monkeypatch.setattr(market_route.market_client, "get_key_metrics_ttm", fake_get_key_metrics_ttm)
    monkeypatch.setattr(market_route.settings, "fmp_api_key", "test-key")

    response = client.get("/market/metrics/UNKNOWN")
    assert response.status_code == 200
    assert response.json() == {}


def test_calendar_invalid_date_returns_422(monkeypatch) -> None:
    monkeypatch.setattr(market_route.settings, "fmp_api_key", "test-key")

    response = client.get("/market/calendar?from_date=not-a-date")
    assert response.status_code == 422


def test_market_endpoints_degrade_on_exception(monkeypatch) -> None:
    async def raise_error(*args, **kwargs):
        raise RuntimeError("FMP down")

    monkeypatch.setattr(market_route.market_client, "get_quote", raise_error)
    monkeypatch.setattr(market_route.market_client, "get_earnings_history", raise_error)
    monkeypatch.setattr(market_route.market_client, "get_earnings_calendar", raise_error)
    monkeypatch.setattr(market_route.market_client, "get_key_metrics_ttm", raise_error)
    monkeypatch.setattr(market_route.settings, "fmp_api_key", "test-key")

    assert client.get("/market/quote/AAPL").json() == {}
    assert client.get("/market/earnings/AAPL").json() == []
    assert client.get("/market/calendar").json() == []
    assert client.get("/market/metrics/AAPL").json() == {}

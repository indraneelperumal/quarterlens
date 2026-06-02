from fastapi.testclient import TestClient

from app.routes import chat as chat_route
from app.main import app

client = TestClient(app)


def test_chat_returns_reply(monkeypatch) -> None:
    async def fake_resolve_ticker(message: str, hint: str | None) -> str:
        return "AAPL"

    async def fake_recent_filings(ticker: str):
        return [], None

    async def fake_search_filing_chunks(message: str, ticker: str):
        return [], None

    async def fake_market_snapshot(ticker: str):
        return {}

    async def fake_news_context(message: str, ticker: str):
        return {"news": [], "sentiment": {"ticker": ticker, "articles": [], "count": 0}}

    monkeypatch.setattr(chat_route, "_resolve_ticker", fake_resolve_ticker)
    monkeypatch.setattr(chat_route, "_recent_filings", fake_recent_filings)
    monkeypatch.setattr(chat_route, "_search_filing_chunks", fake_search_filing_chunks)
    monkeypatch.setattr(chat_route, "_market_snapshot", fake_market_snapshot)
    monkeypatch.setattr(chat_route, "_news_context", fake_news_context)
    monkeypatch.setattr(chat_route.settings, "fmp_api_key", "")
    monkeypatch.setattr(chat_route.settings, "tavily_api_key", "")
    monkeypatch.setattr(chat_route.settings, "alpha_vantage_api_key", "")

    response = client.post("/chat", json={"message": "What is AAPL revenue?", "ticker": "AAPL"})
    assert response.status_code == 200
    data = response.json()
    assert "reply" in data
    assert isinstance(data["reply"], str)
    assert len(data["reply"]) > 0
    assert "sources" in data


def test_chat_includes_phase2_market_and_news_sections(monkeypatch) -> None:
    async def fake_resolve_ticker(message: str, hint: str | None) -> str:
        return "AAPL"

    async def fake_recent_filings(ticker: str):
        return (
            [
                {
                    "accession_number": "0000320193-26-000001",
                    "date": "2026-04-30",
                    "description": "8-K earnings release",
                    "form": "8-K",
                }
            ],
            None,
        )

    async def fake_search_filing_chunks(message: str, ticker: str):
        return (
            [
                {
                    "accession_number": "0000320193-26-000002",
                    "date": "2026-04-30",
                    "form_type": "8-K",
                    "text": "Apple reported quarterly results and discussed services growth.",
                    "source_url": "https://sec.example/apple",
                }
            ],
            None,
        )

    async def fake_market_snapshot(ticker: str):
        return {
            "quote": {
                "price": 210.12,
                "change": 1.5,
                "changesPercentage": 0.72,
                "marketCap": 3_200_000_000_000,
            },
            "earnings_history": [
                {
                    "date": "2026-04-30",
                    "eps": 1.65,
                    "epsEstimated": 1.60,
                    "surprisePct": 3.13,
                }
            ],
            "key_metrics_ttm": {
                "peRatioTTM": 31.2,
                "priceToSalesRatioTTM": 8.1,
                "roeTTM": 1.42,
                "debtToEquityTTM": 1.5,
            },
        }

    async def fake_news_context(message: str, ticker: str):
        return {
            "news": [
                {
                    "title": "Apple shares rise after earnings",
                    "url": "https://news.example/apple",
                    "source": "Example News",
                    "published_date": "2026-05-01",
                }
            ],
            "sentiment": {
                "ticker": "AAPL",
                "count": 1,
                "articles": [{"ticker_sentiment_label": "Bullish"}],
            },
        }

    monkeypatch.setattr(chat_route, "_resolve_ticker", fake_resolve_ticker)
    monkeypatch.setattr(chat_route, "_recent_filings", fake_recent_filings)
    monkeypatch.setattr(chat_route, "_search_filing_chunks", fake_search_filing_chunks)
    monkeypatch.setattr(chat_route, "_market_snapshot", fake_market_snapshot)
    monkeypatch.setattr(chat_route, "_news_context", fake_news_context)
    monkeypatch.setattr(chat_route.settings, "fmp_api_key", "fmp-test")
    monkeypatch.setattr(chat_route.settings, "tavily_api_key", "tvly-test")
    monkeypatch.setattr(chat_route.settings, "alpha_vantage_api_key", "alpha-test")
    # Force Phase 2 fallback formatter (agent loop requires real ANTHROPIC_API_KEY)
    monkeypatch.setattr(chat_route.settings, "anthropic_api_key", "")

    response = client.post("/chat", json={"message": "How is Apple doing?", "ticker": "AAPL"})

    assert response.status_code == 200
    data = response.json()
    reply = data["reply"]
    assert "Recent SEC filings" in reply
    assert "Market snapshot" in reply
    assert "Recent earnings history" in reply
    assert "Key metrics TTM" in reply
    assert "Recent news" in reply
    assert "News sentiment" in reply
    assert "Related context from ingested filings" in reply
    assert any(source.get("type") == "news" for source in data["sources"])


def test_chat_degrades_when_sources_fail(monkeypatch) -> None:
    async def fake_resolve_ticker(message: str, hint: str | None) -> str:
        return "AAPL"

    async def fake_recent_filings(ticker: str):
        return [], "edgar down"

    async def fake_search_filing_chunks(message: str, ticker: str):
        return [], "qdrant down"

    async def fake_market_snapshot(ticker: str):
        raise RuntimeError("market down")

    async def fake_news_context(message: str, ticker: str):
        raise RuntimeError("news down")

    monkeypatch.setattr(chat_route, "_resolve_ticker", fake_resolve_ticker)
    monkeypatch.setattr(chat_route, "_recent_filings", fake_recent_filings)
    monkeypatch.setattr(chat_route, "_search_filing_chunks", fake_search_filing_chunks)
    monkeypatch.setattr(chat_route, "_market_snapshot", fake_market_snapshot)
    monkeypatch.setattr(chat_route, "_news_context", fake_news_context)
    monkeypatch.setattr(chat_route.settings, "fmp_api_key", "")
    monkeypatch.setattr(chat_route.settings, "tavily_api_key", "")
    monkeypatch.setattr(chat_route.settings, "alpha_vantage_api_key", "")
    monkeypatch.setattr(chat_route.settings, "anthropic_api_key", "")

    response = client.post("/chat", json={"message": "How is Apple doing?", "ticker": "AAPL"})

    assert response.status_code == 200
    reply = response.json()["reply"]
    assert "Could not fetch filings from EDGAR: edgar down" in reply
    assert "Vector search unavailable: qdrant down" in reply
    assert "FMP_API_KEY is not configured" in reply
    assert "TAVILY_API_KEY is not configured" in reply
    assert "ALPHA_VANTAGE_API_KEY is not configured" in reply


def test_chat_shows_market_error_when_key_is_configured(monkeypatch) -> None:
    async def fake_resolve_ticker(message: str, hint: str | None) -> str:
        return "AAPL"

    async def fake_recent_filings(ticker: str):
        return [], None

    async def fake_search_filing_chunks(message: str, ticker: str):
        return [], None

    async def fake_market_snapshot(ticker: str):
        return {
            "quote": None,
            "earnings_history": [],
            "key_metrics_ttm": None,
            "errors": {"quote": "FMP plan limit or bad key"},
        }

    async def fake_news_context(message: str, ticker: str):
        return {"news": [], "sentiment": {"ticker": ticker, "articles": [], "count": 0}}

    monkeypatch.setattr(chat_route, "_resolve_ticker", fake_resolve_ticker)
    monkeypatch.setattr(chat_route, "_recent_filings", fake_recent_filings)
    monkeypatch.setattr(chat_route, "_search_filing_chunks", fake_search_filing_chunks)
    monkeypatch.setattr(chat_route, "_market_snapshot", fake_market_snapshot)
    monkeypatch.setattr(chat_route, "_news_context", fake_news_context)
    monkeypatch.setattr(chat_route.settings, "fmp_api_key", "fmp-test")
    monkeypatch.setattr(chat_route.settings, "tavily_api_key", "")
    monkeypatch.setattr(chat_route.settings, "alpha_vantage_api_key", "")
    monkeypatch.setattr(chat_route.settings, "anthropic_api_key", "")

    response = client.post("/chat", json={"message": "How is Apple doing?", "ticker": "AAPL"})

    assert response.status_code == 200
    reply = response.json()["reply"]
    assert "Market snapshot unavailable. Quote error: FMP plan limit or bad key" in reply


def test_filter_relevant_news_keeps_ticker_specific_items() -> None:
    results = chat_route._filter_relevant_news(
        [
            {
                "title": "Friday's big stock stories",
                "content": "General market setup.",
                "url": "https://example.com/market",
                "source": "Example",
            },
            {
                "title": "The 15 best laptops to buy in 2026",
                "content": "Includes Apple MacBook, Microsoft Surface, and other laptops.",
                "url": "https://example.com/laptops",
                "source": "Example",
            },
            {
                "title": "Apple shares rise after earnings",
                "content": "AAPL revenue beat expectations.",
                "url": "https://example.com/apple",
                "source": "Example",
            },
        ],
        "AAPL",
    )

    assert [item["title"] for item in results] == ["Apple shares rise after earnings"]


def test_filter_relevant_news_avoids_substring_false_positive() -> None:
    results = chat_route._filter_relevant_news(
        [
            {
                "title": "Rising labor cost weighs on retail stocks",
                "content": "Analysts say higher wages may pressure shares across the sector.",
                "url": "https://example.com/retail-cost",
                "source": "Example",
            },
            {
                "title": "Costco shares rise after earnings",
                "content": "COST revenue and EPS beat analyst expectations.",
                "url": "https://example.com/costco",
                "source": "Example",
            },
        ],
        "COST",
    )

    assert [item["title"] for item in results] == ["Costco shares rise after earnings"]


def test_filter_relevant_news_keeps_uppercase_ticker_only_headline() -> None:
    results = chat_route._filter_relevant_news(
        [
            {
                "title": "COST revenue beats estimates",
                "content": "Shares rose after quarterly results topped analyst expectations.",
                "url": "https://example.com/earnings",
                "source": "Example",
            },
            {
                "title": "Labor cost weighs on retail stocks",
                "content": "Analysts discuss wage pressure across retail.",
                "url": "https://example.com/labor",
                "source": "Example",
            },
        ],
        "COST",
    )

    assert [item["title"] for item in results] == ["COST revenue beats estimates"]


def test_filter_relevant_news_unknown_ticker_requires_uppercase_token() -> None:
    results = chat_route._filter_relevant_news(
        [
            {
                "title": "Cat food maker shares rise after earnings",
                "content": "A pet food stock moved after quarterly results.",
                "url": "https://example.com/cat-food",
                "source": "Example",
            },
            {
                "title": "CAT revenue beats estimates",
                "content": "Shares rose after quarterly results.",
                "url": "https://example.com/cat",
                "source": "Example",
            },
        ],
        "CAT",
    )

    assert [item["title"] for item in results] == ["CAT revenue beats estimates"]


def test_chat_handles_partial_filing_payloads(monkeypatch) -> None:
    async def fake_resolve_ticker(message: str, hint: str | None) -> str:
        return "AAPL"

    async def fake_recent_filings(ticker: str):
        return ([{"form": "8-K"}], None)

    async def fake_search_filing_chunks(message: str, ticker: str):
        return [], None

    async def fake_market_snapshot(ticker: str):
        return {}

    async def fake_news_context(message: str, ticker: str):
        return {"news": [], "sentiment": {"ticker": ticker, "articles": [], "count": 0}}

    monkeypatch.setattr(chat_route, "_resolve_ticker", fake_resolve_ticker)
    monkeypatch.setattr(chat_route, "_recent_filings", fake_recent_filings)
    monkeypatch.setattr(chat_route, "_search_filing_chunks", fake_search_filing_chunks)
    monkeypatch.setattr(chat_route, "_market_snapshot", fake_market_snapshot)
    monkeypatch.setattr(chat_route, "_news_context", fake_news_context)
    monkeypatch.setattr(chat_route.settings, "fmp_api_key", "")
    monkeypatch.setattr(chat_route.settings, "tavily_api_key", "")
    monkeypatch.setattr(chat_route.settings, "alpha_vantage_api_key", "")
    monkeypatch.setattr(chat_route.settings, "anthropic_api_key", "")

    response = client.post("/chat", json={"message": "Did Apple file?", "ticker": "AAPL"})

    assert response.status_code == 200
    data = response.json()
    assert "8-K filing" in data["reply"]
    assert data["sources"] == []


def test_chat_no_ticker_returns_helpful_response(monkeypatch) -> None:
    async def fake_resolve_ticker(message: str, hint: str | None) -> None:
        return None

    monkeypatch.setattr(chat_route, "_resolve_ticker", fake_resolve_ticker)

    response = client.post("/chat", json={"message": "What happened recently?"})

    assert response.status_code == 200
    assert "Could not identify a company ticker" in response.json()["reply"]

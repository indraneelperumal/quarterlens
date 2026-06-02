from __future__ import annotations

import json

import httpx
import pytest

from app.mcp import news

_REAL_ASYNC_CLIENT = httpx.AsyncClient


class MockAsyncClient:
    def __init__(self, transport: httpx.MockTransport, **_: object) -> None:
        self._client = _REAL_ASYNC_CLIENT(transport=transport)

    async def __aenter__(self) -> "MockAsyncClient":
        await self._client.__aenter__()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self._client.__aexit__(*args)

    async def post(self, *args: object, **kwargs: object) -> httpx.Response:
        return await self._client.post(*args, **kwargs)

    async def get(self, *args: object, **kwargs: object) -> httpx.Response:
        return await self._client.get(*args, **kwargs)


def patch_async_client(monkeypatch, transport: httpx.MockTransport) -> None:
    def factory(**kwargs: object) -> MockAsyncClient:
        return MockAsyncClient(transport, **kwargs)

    monkeypatch.setattr(news.httpx, "AsyncClient", factory)


async def test_search_news_missing_key_returns_empty() -> None:
    assert await news.search_news("AAPL earnings", api_key="") == []
    assert await news.search_news("AAPL earnings", api_key="   ") == []


async def test_search_news_posts_tavily_request_and_normalizes(monkeypatch) -> None:
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers["Authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Apple earnings rise",
                        "url": "https://example.com/apple",
                        "content": "Apple reported stronger earnings.",
                        "score": 0.91,
                        "published_date": "2026-01-31",
                    }
                ]
            },
        )

    patch_async_client(monkeypatch, httpx.MockTransport(handler))

    results = await news.search_news(
        "AAPL earnings",
        api_key="tvly-test",
        max_results=99,
        days=99,
    )

    assert captured["url"] == "https://api.tavily.com/search"
    assert captured["auth"] == "Bearer tvly-test"
    assert captured["body"] == {
        "query": "AAPL earnings",
        "topic": "news",
        "search_depth": "basic",
        "max_results": 10,
        "days": 30,
        "include_answer": False,
        "include_raw_content": False,
        "include_images": False,
    }
    assert results == [
        {
            "title": "Apple earnings rise",
            "url": "https://example.com/apple",
            "source": "https://example.com/apple",
            "published_date": "2026-01-31",
            "content": "Apple reported stronger earnings.",
            "score": 0.91,
        }
    ]


async def test_search_news_rejects_bad_response_shape(monkeypatch) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": {"not": "a list"}})

    patch_async_client(monkeypatch, httpx.MockTransport(handler))

    with pytest.raises(RuntimeError, match="Unexpected Tavily results shape"):
        await news.search_news("AAPL earnings", api_key="tvly-test")


async def test_search_news_http_error_degrades_to_empty(monkeypatch) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate limit"})

    patch_async_client(monkeypatch, httpx.MockTransport(handler))

    assert await news.search_news("AAPL earnings", api_key="tvly-test") == []


async def test_get_news_sentiment_missing_key_returns_empty_shape() -> None:
    assert await news.get_news_sentiment(" aapl ", api_key="") == {
        "ticker": "AAPL",
        "articles": [],
        "count": 0,
    }
    assert await news.get_news_sentiment(" aapl ", api_key="   ") == {
        "ticker": "AAPL",
        "articles": [],
        "count": 0,
    }


async def test_get_news_sentiment_requires_ticker() -> None:
    with pytest.raises(ValueError, match="ticker is required"):
        await news.get_news_sentiment(" ", api_key="alpha-test")


async def test_get_news_sentiment_gets_alpha_request_and_normalizes(monkeypatch) -> None:
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["params"] = dict(request.url.params)
        return httpx.Response(
            200,
            json={
                "feed": [
                    {
                        "title": "Nvidia news",
                        "url": "https://example.com/nvda",
                        "source": "Example News",
                        "time_published": "20260131T120000",
                        "summary": "Nvidia shares moved after earnings.",
                        "overall_sentiment_score": "0.31",
                        "overall_sentiment_label": "Somewhat-Bullish",
                        "ticker_sentiment": [
                            {
                                "ticker": "NVDA",
                                "relevance_score": "0.88",
                                "ticker_sentiment_score": "0.45",
                                "ticker_sentiment_label": "Bullish",
                            }
                        ],
                    }
                ]
            },
        )

    patch_async_client(monkeypatch, httpx.MockTransport(handler))

    result = await news.get_news_sentiment("nvda", api_key="alpha-test", limit=99)

    assert captured["url"].startswith("https://www.alphavantage.co/query")
    assert captured["params"] == {
        "function": "NEWS_SENTIMENT",
        "tickers": "NVDA",
        "sort": "LATEST",
        "limit": "50",
        "apikey": "alpha-test",
    }
    assert result == {
        "ticker": "NVDA",
        "count": 1,
        "articles": [
            {
                "title": "Nvidia news",
                "url": "https://example.com/nvda",
                "source": "Example News",
                "published_at": "20260131T120000",
                "summary": "Nvidia shares moved after earnings.",
                "overall_sentiment_score": "0.31",
                "overall_sentiment_label": "Somewhat-Bullish",
                "ticker_sentiment_score": "0.45",
                "ticker_sentiment_label": "Bullish",
                "relevance_score": "0.88",
            }
        ],
    }


async def test_get_news_sentiment_raises_on_provider_error(monkeypatch) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"Note": "rate limit reached"})

    patch_async_client(monkeypatch, httpx.MockTransport(handler))

    with pytest.raises(RuntimeError, match="rate limit reached"):
        await news.get_news_sentiment("AAPL", api_key="alpha-test")


async def test_get_news_sentiment_http_error_degrades_to_empty(monkeypatch) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "bad key"})

    patch_async_client(monkeypatch, httpx.MockTransport(handler))

    assert await news.get_news_sentiment("AAPL", api_key="alpha-test") == {
        "ticker": "AAPL",
        "articles": [],
        "count": 0,
    }

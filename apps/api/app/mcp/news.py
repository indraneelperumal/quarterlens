"""Direct async REST wrappers for financial news sources.

Tavily provides recent web/news search. Alpha Vantage provides market news
sentiment. These are direct HTTP wrappers in Phase 2; chat orchestration will
call them alongside MCP-backed filings and market data in Step 5.
"""
from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

import httpx

_TAVILY_SEARCH_URL = "https://api.tavily.com/search"
_ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"
_TIMEOUT = 30.0


def _clamp(value: int, lower: int, upper: int) -> int:
    return max(lower, min(value, upper))


def _domain_from_url(url: str) -> str:
    try:
        host = urlparse(url).hostname or url
        return host.removeprefix("www.")
    except Exception:
        return url


def _normalize_tavily_result(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": item.get("title", ""),
        "url": item.get("url", ""),
        "source": item.get("source") or _domain_from_url(item.get("url", "")),
        "published_date": item.get("published_date") or item.get("published_time", ""),
        "content": item.get("content", ""),
        "score": item.get("score"),
    }


def _alpha_ticker_sentiment(article: dict[str, Any], ticker: str) -> dict[str, Any]:
    ticker = ticker.upper()
    for item in article.get("ticker_sentiment", []):
        if item.get("ticker", "").upper() == ticker:
            return {
                "ticker_sentiment_score": item.get("ticker_sentiment_score"),
                "ticker_sentiment_label": item.get("ticker_sentiment_label"),
                "relevance_score": item.get("relevance_score"),
            }
    return {
        "ticker_sentiment_score": None,
        "ticker_sentiment_label": None,
        "relevance_score": None,
    }


def _normalize_alpha_article(article: dict[str, Any], ticker: str) -> dict[str, Any]:
    sentiment = _alpha_ticker_sentiment(article, ticker)
    return {
        "title": article.get("title", ""),
        "url": article.get("url", ""),
        "source": article.get("source", ""),
        "published_at": article.get("time_published", ""),
        "summary": article.get("summary", ""),
        "overall_sentiment_score": article.get("overall_sentiment_score"),
        "overall_sentiment_label": article.get("overall_sentiment_label"),
        **sentiment,
    }


def _raise_for_provider_error(data: dict[str, Any]) -> None:
    for key in ("Error Message", "Note", "Information"):
        if key in data:
            raise RuntimeError(str(data[key]))


async def search_news(
    query: str,
    api_key: str,
    max_results: int = 5,
    days: int = 7,
) -> list[dict[str, Any]]:
    """Return recent finance/news search results from Tavily.

    Missing API keys return an empty list so Step 5 can degrade gracefully when
    news search is not configured.
    """
    query = query.strip()
    api_key = api_key.strip()
    if not query or not api_key:
        return []

    limit = _clamp(max_results, 1, 10)
    days = _clamp(days, 1, 30)
    payload = {
        "query": query,
        "topic": "news",
        "search_depth": "basic",
        "max_results": limit,
        "days": days,
        "include_answer": False,
        "include_raw_content": False,
        "include_images": False,
    }
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            response = await client.post(_TAVILY_SEARCH_URL, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, json.JSONDecodeError, ValueError):
        return []

    if not isinstance(data, dict):
        raise RuntimeError("Unexpected Tavily response shape")

    results = data.get("results", [])
    if not isinstance(results, list):
        raise RuntimeError("Unexpected Tavily results shape")

    return [_normalize_tavily_result(item) for item in results[:limit] if isinstance(item, dict)]


async def get_news_sentiment(
    ticker: str,
    api_key: str,
    limit: int = 10,
) -> dict[str, Any]:
    """Return normalized Alpha Vantage news sentiment for *ticker*.

    Missing API keys return a shaped empty response so callers can include the
    source status without treating it as a hard failure.
    """
    ticker = ticker.upper().strip()
    api_key = api_key.strip()
    if not ticker:
        raise ValueError("ticker is required")
    if not api_key:
        return {"ticker": ticker, "articles": [], "count": 0}

    limit = _clamp(limit, 1, 50)
    params = {
        "function": "NEWS_SENTIMENT",
        "tickers": ticker,
        "sort": "LATEST",
        "limit": limit,
        "apikey": api_key,
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            response = await client.get(_ALPHA_VANTAGE_URL, params=params)
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, json.JSONDecodeError, ValueError):
        return {"ticker": ticker, "articles": [], "count": 0}

    if not isinstance(data, dict):
        raise RuntimeError("Unexpected Alpha Vantage response shape")
    _raise_for_provider_error(data)

    feed = data.get("feed", [])
    if not isinstance(feed, list):
        raise RuntimeError("Unexpected Alpha Vantage feed shape")

    articles = [
        _normalize_alpha_article(article, ticker)
        for article in feed[:limit]
        if isinstance(article, dict)
    ]
    return {
        "ticker": ticker,
        "articles": articles,
        "count": len(articles),
    }

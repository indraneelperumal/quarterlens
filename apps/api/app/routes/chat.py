from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from datetime import date, timedelta
from functools import partial
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agent.loop import run_agent
from app.config import settings
from app.mcp import client as mcp_client
from app.mcp import market_client, news
from app.rag.embedder import embed_texts
from app.rag.store import VectorStore

router = APIRouter(prefix="/chat", tags=["chat"])
log = logging.getLogger(__name__)

_COMPANY_TERMS: dict[str, tuple[str, ...]] = {
    "AAPL": ("apple", "aapl"),
    "GOOGL": ("alphabet", "google", "googl"),
    "MSFT": ("microsoft", "msft"),
    "NVDA": ("nvidia", "nvda"),
    "AMZN": ("amazon", "amzn"),
    "JPM": ("jpmorgan", "jp morgan", "jpm"),
    "UNH": ("unitedhealth", "united health", "unh"),
    "XOM": ("exxon", "exxonmobil", "xom"),
    "COST": ("costco",),
}
_NEWS_CONTEXT_TERMS = (
    "earnings",
    "revenue",
    "profit",
    "eps",
    "shares",
    "stock",
    "investor",
    "analyst",
    "forecast",
    "guidance",
    "quarter",
    "results",
)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    ticker: str | None = Field(None, description="Optional ticker hint, e.g. AAPL")


class ChatResponse(BaseModel):
    reply: str
    sources: list[dict] = Field(default_factory=list)


async def _resolve_ticker(message: str, hint: str | None) -> str | None:
    """Return uppercase ticker: message extraction → hint fallback → None.

    Message extraction takes priority so that typing "nvidia" overrides a
    stale dropdown selection. The hint is the fallback for generic queries
    like "what happened recently?" where no company is named.
    """
    if settings.anthropic_api_key:
        try:
            import anthropic
            from app.utils.ticker_resolver import extract_tickers

            ac = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
            tickers = await extract_tickers(message, ac)
            if tickers:
                return tickers[0]
        except Exception as exc:
            log.warning("Ticker extraction failed: %s", exc)
    if hint:
        return hint.upper()
    return None


async def _recent_filings(ticker: str) -> tuple[list[dict], str | None]:
    cutoff = (date.today() - timedelta(days=90)).isoformat()
    try:
        raw = await mcp_client.recent_filings(
            ticker, "8-K", limit=10, user_agent=settings.sec_edgar_user_agent
        )
        # Explicit None guard - ISO YYYY-MM-DD sorts lexicographically
        return [f for f in raw if f.get("date") and f["date"] >= cutoff], None
    except Exception as exc:
        return [], str(exc)


async def _search_filing_chunks(message: str, ticker: str) -> tuple[list[dict], str | None]:
    try:
        loop = asyncio.get_running_loop()
        vec = await loop.run_in_executor(None, partial(embed_texts, [message]))
        chunks = await loop.run_in_executor(None, partial(_qdrant_search, vec[0], ticker))
        return chunks, None
    except Exception as exc:
        return [], str(exc)


def _qdrant_search(vector: list[float], ticker: str) -> list[dict]:
    store = VectorStore(settings.qdrant_url)
    store.ensure_collection()
    return store.search(vector, limit=5, ticker=ticker, form_type="8-K")


async def _market_snapshot(ticker: str) -> dict[str, Any]:
    api_key = settings.fmp_api_key.strip()
    if not api_key:
        return {}
    quote, earnings, metrics = await asyncio.gather(
        market_client.get_quote(ticker, api_key=api_key),
        market_client.get_earnings_history(ticker, limit=4, api_key=api_key),
        market_client.get_key_metrics_ttm(ticker, api_key=api_key),
        return_exceptions=True,
    )
    return {
        "quote": None if isinstance(quote, Exception) else quote,
        "earnings_history": [] if isinstance(earnings, Exception) else earnings,
        "key_metrics_ttm": None if isinstance(metrics, Exception) else metrics,
        "errors": {
            "quote": str(quote) if isinstance(quote, Exception) else None,
            "earnings_history": str(earnings) if isinstance(earnings, Exception) else None,
            "key_metrics_ttm": str(metrics) if isinstance(metrics, Exception) else None,
        },
    }


async def _news_context(message: str, ticker: str) -> dict[str, Any]:
    api_key = settings.tavily_api_key.strip()
    company_terms = _COMPANY_TERMS.get(ticker.upper(), ())
    company_name = company_terms[0] if company_terms else ticker.upper()
    query = f"{company_name} {ticker} earnings stock recent news"
    tavily_results, sentiment = await asyncio.gather(
        news.search_news(query, api_key=api_key, max_results=8),
        news.get_news_sentiment(
            ticker, api_key=settings.alpha_vantage_api_key.strip(), limit=5
        ),
        return_exceptions=True,
    )
    filtered_news = (
        []
        if isinstance(tavily_results, Exception)
        else _filter_relevant_news(tavily_results, ticker)
    )
    return {
        "news": filtered_news[:5],
        "sentiment": (
            {"ticker": ticker, "articles": [], "count": 0}
            if isinstance(sentiment, Exception)
            else sentiment
        ),
        "errors": {
            "news": str(tavily_results) if isinstance(tavily_results, Exception) else None,
            "sentiment": str(sentiment) if isinstance(sentiment, Exception) else None,
        },
    }


def _filter_relevant_news(items: list[dict], ticker: str) -> list[dict]:
    terms = _COMPANY_TERMS.get(ticker.upper(), ())
    relevant: list[dict] = []
    for item in items:
        raw_haystack = " ".join(
            str(item.get(field, ""))
            for field in ("title", "content", "url", "source")
        )
        haystack = raw_haystack.lower()
        has_company = _contains_ticker(raw_haystack, ticker) or any(
            _contains_term(haystack, term) for term in terms
        )
        has_market_context = any(_contains_term(haystack, term) for term in _NEWS_CONTEXT_TERMS)
        if has_company and has_market_context:
            relevant.append(item)
    return relevant


def _contains_ticker(text: str, ticker: str) -> bool:
    return re.search(rf"(?<![A-Z0-9]){re.escape(ticker.upper())}(?![A-Z0-9])", text) is not None


def _contains_term(text: str, term: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(term.lower())}(?![a-z0-9])", text) is not None


def _fmt_number(value: Any) -> str:
    if value is None or value == "":
        return "n/a"
    if isinstance(value, float):
        return f"{value:,.2f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def _fmt_large(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(v):
        return "n/a"
    a = abs(v)
    if a >= 1e12:
        return f"${v / 1e12:.2f}T"
    if a >= 1e9:
        return f"${v / 1e9:.2f}B"
    if a >= 1e6:
        return f"${v / 1e6:.2f}M"
    return f"${v:,.2f}"


def _fmt_pub_date(raw: str) -> str:
    """Trim RFC 2822 dates like 'Thu, 28 May 2026 23:49:51 GMT' to '28 May 2026'.
    Returns the raw string unchanged for any format without a leading weekday comma.
    """
    if not raw:
        return ""
    if "," not in raw:
        return raw
    after_comma = raw.split(",", 1)[1].strip()
    return " ".join(after_comma.split()[:3])


def _build_sources(filings: list[dict], chunks: list[dict], news_items: list[dict]) -> list[dict]:
    sources: list[dict] = []
    for f in filings:
        accession = f.get("accession_number", "")
        if not accession:
            continue
        sources.append(
            {
                "accession_number": accession,
                "date": f.get("date", ""),
                "form": f.get("form", "8-K"),
            }
        )

    seen_acc = {s["accession_number"] for s in sources}
    for c in chunks:
        acc = c.get("accession_number", "")
        if acc and acc not in seen_acc:
            sources.append(
                {
                    "accession_number": acc,
                    "date": c.get("date", ""),
                    "form": c.get("form_type", "8-K"),
                    "source_url": c.get("source_url", ""),
                }
            )
            seen_acc.add(acc)

    seen_urls: set[str] = set()
    for item in news_items:
        url = item.get("url", "")
        if url and url not in seen_urls:
            sources.append(
                {
                    "type": "news",
                    "title": item.get("title", ""),
                    "source_url": url,
                    "published_date": item.get("published_date", ""),
                }
            )
            seen_urls.add(url)
    return sources


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Phase 3: Claude agent loop synthesis with Phase 2 formatter as fallback."""

    # ── 1. Ticker resolution ────────────────────────────────────────────────
    ticker = await _resolve_ticker(request.message, request.ticker)
    if not ticker:
        return ChatResponse(
            reply=(
                "Could not identify a company ticker in your message. "
                "Include a ticker hint (e.g. AAPL) or name the company clearly."
            ),
            sources=[],
        )

    # ── 2. Phase 3: Claude agent synthesis (when ANTHROPIC_API_KEY is set) ──
    if settings.anthropic_api_key:
        try:
            reply = await run_agent(request.message, ticker, settings)
            return ChatResponse(reply=reply, sources=[])
        except Exception as exc:
            log.warning("Agent loop failed, falling back to Phase 2 formatter: %s", exc)

    # ── 3. Phase 2 fallback: gather all sources concurrently ────────────────
    filings_result, chunks_result, market_data, news_data = await asyncio.gather(
        _recent_filings(ticker),
        _search_filing_chunks(request.message, ticker),
        _market_snapshot(ticker),
        _news_context(request.message, ticker),
        return_exceptions=True,
    )

    filings: list[dict] = []
    mcp_error: str | None = None
    if isinstance(filings_result, Exception):
        mcp_error = str(filings_result)
    else:
        filings, mcp_error = filings_result

    chunks: list[dict] = []
    qdrant_error: str | None = None
    if isinstance(chunks_result, Exception):
        qdrant_error = str(chunks_result)
    else:
        chunks, qdrant_error = chunks_result

    market_data = {} if isinstance(market_data, Exception) else market_data
    news_data = {} if isinstance(news_data, Exception) else news_data
    has_fmp_key = bool(settings.fmp_api_key.strip())
    has_tavily_key = bool(settings.tavily_api_key.strip())
    has_alpha_vantage_key = bool(settings.alpha_vantage_api_key.strip())

    quote = market_data.get("quote")
    earnings_history = market_data.get("earnings_history", [])
    key_metrics = market_data.get("key_metrics_ttm")
    market_errors = market_data.get("errors", {})
    news_items = news_data.get("news", [])
    sentiment = news_data.get("sentiment", {"ticker": ticker, "articles": [], "count": 0})

    # ── 4. Phase 2 format reply ─────────────────────────────────────────────
    lines: list[str] = []

    if filings:
        lines.append(f"Recent SEC filings: {ticker} filed {len(filings)} 8-K(s) in the last 90 days:")
        for f in filings:
            desc = f.get("description") or f.get("accession_number", "8-K filing")
            lines.append(f"  • {f.get('date', '?')}  {desc}")
    elif mcp_error:
        lines.append(f"Could not fetch filings from EDGAR: {mcp_error}")
    else:
        lines.append(f"No 8-K filings found for {ticker} in the last 90 days.")

    if quote:
        lines.append("Market snapshot:")
        lines.append(
            "  • "
            f"Price: ${_fmt_number(quote.get('price'))}; "
            f"change: {_fmt_number(quote.get('change'))} "
            f"({_fmt_number(quote.get('changesPercentage'))}%); "
            f"market cap: {_fmt_large(quote.get('marketCap'))}"
        )
    elif has_fmp_key:
        error = market_errors.get("quote") if isinstance(market_errors, dict) else None
        lines.append(
            "Market snapshot unavailable."
            + (f" Quote error: {error}" if error else "")
        )

    if earnings_history:
        lines.append("Recent earnings history:")
        for item in earnings_history[:4]:
            lines.append(
                "  • "
                f"{item.get('date', '?')}: EPS {_fmt_number(item.get('eps'))} "
                f"vs estimate {_fmt_number(item.get('epsEstimated'))}; "
                f"surprise {_fmt_number(item.get('surprisePct'))}%"
            )

    if key_metrics:
        lines.append("Key metrics TTM:")
        metrics_bits = [
            f"P/E: {_fmt_number(key_metrics.get('peRatioTTM'))}",
            f"EV/S: {_fmt_number(key_metrics.get('evToSalesTTM'))}",
            f"ROE: {_fmt_number(key_metrics.get('roeTTM'))}",
            f"Debt/equity: {_fmt_number(key_metrics.get('debtToEquityTTM'))}",
        ]
        lines.append("  • " + "; ".join(metrics_bits))

    if news_items:
        lines.append("Recent news:")
        for item in news_items[:5]:
            title = item.get("title") or item.get("url", "Untitled")
            source = item.get("source", "")
            published = _fmt_pub_date(item.get("published_date", ""))
            suffix = " - ".join(part for part in (source, published) if part)
            lines.append(f"  • {title}" + (f" ({suffix})" if suffix else ""))
    elif has_tavily_key:
        lines.append(f"No ticker-specific recent news found for {ticker}.")

    sentiment_articles = sentiment.get("articles", []) if isinstance(sentiment, dict) else []
    if sentiment_articles:
        labels = [
            article.get("ticker_sentiment_label") or article.get("overall_sentiment_label")
            for article in sentiment_articles
            if article.get("ticker_sentiment_label") or article.get("overall_sentiment_label")
        ]
        label_summary = ", ".join(labels[:3]) if labels else "n/a"
        lines.append(
            f"News sentiment: {len(sentiment_articles)} article(s), recent labels: {label_summary}"
        )
    elif has_alpha_vantage_key:
        lines.append("News sentiment unavailable.")

    if chunks:
        lines.append(f"Related context from ingested filings ({len(chunks)} chunk(s)):")
        for c in chunks[:3]:
            snippet = c.get("text", "")[:200].replace("\n", " ")
            lines.append(f"  [{c.get('date', '?')}] {snippet}...")
    elif qdrant_error:
        lines.append(f"(Vector search unavailable: {qdrant_error})")

    if not has_fmp_key:
        lines.append("(Market data unavailable: FMP_API_KEY is not configured.)")
    if not has_tavily_key:
        lines.append("(Recent news unavailable: TAVILY_API_KEY is not configured.)")
    if not has_alpha_vantage_key:
        lines.append("(News sentiment unavailable: ALPHA_VANTAGE_API_KEY is not configured.)")

    sources = _build_sources(filings, chunks, news_items)
    return ChatResponse(reply="\n".join(lines), sources=sources)


@router.post("/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    """SSE endpoint: yields the agent reply as a single data chunk then [DONE]."""

    async def event_generator():
        ticker = await _resolve_ticker(request.message, request.ticker)
        if not ticker:
            yield f"data: {json.dumps({'text': 'Could not identify a ticker.'})}\n\n"
            yield "data: [DONE]\n\n"
            return
        try:
            reply = await run_agent(request.message, ticker, settings)
        except Exception as exc:
            log.warning("Agent loop error in /stream: %s", exc)
            reply = f"Error: {exc}"
        yield f"data: {json.dumps({'text': reply})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

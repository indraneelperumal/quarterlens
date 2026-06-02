"""Tests for the Phase 3 Claude agent loop."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.agent import loop as agent_loop
from app.agent.loop import run_agent
from app.config import settings
from app.main import app
from app.routes import chat as chat_route

client = TestClient(app)


# ---------------------------------------------------------------------------
# run_agent — unit tests (no real API calls)
# ---------------------------------------------------------------------------


def test_run_agent_no_key_returns_fallback():
    """run_agent returns a non-empty fallback string when ANTHROPIC_API_KEY is unset."""

    class FakeSettings:
        anthropic_api_key = ""
        claude_model = "claude-sonnet-4-6"
        claude_max_tokens = 4096
        claude_max_tool_rounds = 5
        sec_edgar_user_agent = "test agent@test.com"
        fmp_api_key = ""
        tavily_api_key = ""
        alpha_vantage_api_key = ""

    import asyncio
    text, citations = asyncio.run(
        run_agent("How is Apple doing?", "AAPL", FakeSettings())
    )
    assert isinstance(text, str)
    assert len(text) > 0
    assert "ANTHROPIC_API_KEY" in text
    assert citations == []


def test_run_agent_uses_tool_results(monkeypatch):
    """run_agent calls execute_tool and incorporates results into final reply."""
    fixture_quote = {"symbol": "AAPL", "price": 210.12, "marketCap": 3_200_000_000_000}

    async def fake_execute_tool(block, ticker, cfg):
        return fixture_quote

    # Build fake Anthropic response: first call returns tool_use, second returns text
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.id = "tool_123"
    tool_block.name = "get_stock_quote"
    tool_block.input = {"ticker": "AAPL"}

    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = f"Apple price is $210.12 per the quote data."

    tool_response = MagicMock()
    tool_response.stop_reason = "tool_use"
    tool_response.content = [tool_block]

    final_response = MagicMock()
    final_response.stop_reason = "end_turn"
    final_response.content = [text_block]

    mock_create = AsyncMock(side_effect=[tool_response, final_response])

    class FakeSettings:
        anthropic_api_key = "test-key"
        claude_model = "claude-sonnet-4-6"
        claude_max_tokens = 4096
        claude_max_tool_rounds = 5
        sec_edgar_user_agent = "test agent@test.com"
        fmp_api_key = "fmp-test"
        tavily_api_key = ""
        alpha_vantage_api_key = ""

    monkeypatch.setattr(agent_loop, "execute_tool", fake_execute_tool)

    with patch("anthropic.AsyncAnthropic") as MockAnthropic:
        instance = MockAnthropic.return_value
        instance.messages.create = mock_create

        import asyncio
        text, citations = asyncio.run(
            run_agent("What is Apple's stock price?", "AAPL", FakeSettings())
        )

    assert "210.12" in text
    assert mock_create.call_count == 2


def test_run_agent_exhausted_rounds_forces_final_call(monkeypatch):
    """When all rounds return tool_use, a forced final synthesis call is made."""
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.id = "tool_456"
    tool_block.name = "get_stock_quote"
    tool_block.input = {"ticker": "AAPL"}

    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "Final synthesized answer."

    tool_response = MagicMock()
    tool_response.stop_reason = "tool_use"
    tool_response.content = [tool_block]

    forced_response = MagicMock()
    forced_response.stop_reason = "end_turn"
    forced_response.content = [text_block]

    class FakeSettings:
        anthropic_api_key = "test-key"
        claude_model = "claude-sonnet-4-6"
        claude_max_tokens = 4096
        claude_max_tool_rounds = 2
        sec_edgar_user_agent = "test agent@test.com"
        fmp_api_key = ""
        tavily_api_key = ""
        alpha_vantage_api_key = ""

    async def fake_execute_tool(block, ticker, cfg):
        return {}

    monkeypatch.setattr(agent_loop, "execute_tool", fake_execute_tool)

    # 2 tool_use rounds + 1 forced final = 3 total calls
    mock_create = AsyncMock(side_effect=[tool_response, tool_response, forced_response])

    with patch("anthropic.AsyncAnthropic") as MockAnthropic:
        instance = MockAnthropic.return_value
        instance.messages.create = mock_create

        import asyncio
        text, citations = asyncio.run(
            run_agent("Summarize Apple.", "AAPL", FakeSettings())
        )

    assert text == "Final synthesized answer."
    assert mock_create.call_count == 3
    # Last call must include tool_choice={"type": "none"}
    last_kwargs = mock_create.call_args_list[-1].kwargs
    assert last_kwargs.get("tool_choice") == {"type": "none"}


# ---------------------------------------------------------------------------
# /chat endpoint — agent path
# ---------------------------------------------------------------------------


def test_chat_endpoint_with_agent(monkeypatch):
    """POST /chat returns run_agent output when ANTHROPIC_API_KEY is set."""

    async def fake_resolve_ticker(message: str, hint: str | None) -> str:
        return "AAPL"

    async def fake_run_agent(message: str, ticker, cfg, history=None):
        return ("Investor-grade prose about Apple.", [])

    monkeypatch.setattr(chat_route, "_resolve_ticker", fake_resolve_ticker)
    monkeypatch.setattr(chat_route, "run_agent", fake_run_agent)
    monkeypatch.setattr(chat_route.settings, "anthropic_api_key", "test-key")

    response = client.post("/chat", json={"message": "How is Apple doing?", "ticker": "AAPL"})

    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == "Investor-grade prose about Apple."
    assert data["citations"] == []


def test_chat_endpoint_agent_exception_falls_back_to_phase2(monkeypatch):
    """When run_agent raises, /chat falls back to the Phase 2 formatter."""

    async def fake_resolve_ticker(message: str, hint: str | None) -> str:
        return "AAPL"

    async def fake_run_agent(message: str, ticker, cfg, history=None):
        raise RuntimeError("simulated agent failure")

    async def fake_recent_filings(ticker: str):
        return [], None

    async def fake_search_filing_chunks(message: str, ticker: str):
        return [], None

    async def fake_market_snapshot(ticker: str):
        return {}

    async def fake_news_context(message: str, ticker: str):
        return {"news": [], "sentiment": {"ticker": ticker, "articles": [], "count": 0}}

    monkeypatch.setattr(chat_route, "_resolve_ticker", fake_resolve_ticker)
    monkeypatch.setattr(chat_route, "run_agent", fake_run_agent)
    monkeypatch.setattr(chat_route, "_recent_filings", fake_recent_filings)
    monkeypatch.setattr(chat_route, "_search_filing_chunks", fake_search_filing_chunks)
    monkeypatch.setattr(chat_route, "_market_snapshot", fake_market_snapshot)
    monkeypatch.setattr(chat_route, "_news_context", fake_news_context)
    monkeypatch.setattr(chat_route.settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(chat_route.settings, "fmp_api_key", "")
    monkeypatch.setattr(chat_route.settings, "tavily_api_key", "")
    monkeypatch.setattr(chat_route.settings, "alpha_vantage_api_key", "")

    response = client.post("/chat", json={"message": "How is Apple doing?", "ticker": "AAPL"})

    assert response.status_code == 200
    data = response.json()
    # Phase 2 formatter produces text about AAPL; not an empty string or error
    assert isinstance(data["answer"], str)
    assert len(data["answer"]) > 0


# ---------------------------------------------------------------------------
# /chat/stream endpoint
# ---------------------------------------------------------------------------


def test_chat_stream_endpoint_sse_format(monkeypatch):
    """POST /chat/stream yields data: lines followed by data: [DONE]."""

    async def fake_resolve_ticker(message: str, hint: str | None) -> str:
        return "NVDA"

    async def fake_run_agent(message: str, ticker, cfg, history=None):
        return ("NVDA had strong earnings last quarter.", [])

    monkeypatch.setattr(chat_route, "_resolve_ticker", fake_resolve_ticker)
    monkeypatch.setattr(chat_route, "run_agent", fake_run_agent)
    monkeypatch.setattr(chat_route.settings, "anthropic_api_key", "test-key")

    response = client.post(
        "/chat/stream",
        json={"message": "What were NVDA last 4 quarters EPS?", "ticker": "NVDA"},
    )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    body = response.text
    assert "data: " in body
    assert "data: [DONE]" in body

    data_lines = [
        line[6:] for line in body.splitlines() if line.startswith("data: ") and line != "data: [DONE]"
    ]
    # Word-by-word: multiple text events + 1 citations event
    assert len(data_lines) >= 2
    text_events = [json.loads(d) for d in data_lines if "text" in json.loads(d)]
    citations_events = [json.loads(d) for d in data_lines if "citations" in json.loads(d)]
    full_text = "".join(e["text"] for e in text_events).strip()
    assert full_text == "NVDA had strong earnings last quarter."
    assert len(citations_events) == 1
    assert citations_events[0]["citations"] == []


def test_chat_stream_no_ticker_still_calls_agent(monkeypatch):
    """When ticker resolution fails, /stream still calls run_agent with ticker=None."""

    async def fake_resolve_ticker(message: str, hint: str | None) -> None:
        return None

    async def fake_run_agent(message: str, ticker, cfg, history=None):
        assert ticker is None
        return ("I can help with general finance questions too.", [])

    monkeypatch.setattr(chat_route, "_resolve_ticker", fake_resolve_ticker)
    monkeypatch.setattr(chat_route, "run_agent", fake_run_agent)
    monkeypatch.setattr(chat_route.settings, "anthropic_api_key", "test-key")

    response = client.post("/chat/stream", json={"message": "What happened recently?"})

    assert response.status_code == 200
    body = response.text
    assert "data: [DONE]" in body
    data_lines = [
        line[6:] for line in body.splitlines() if line.startswith("data: ") and line != "data: [DONE]"
    ]
    assert len(data_lines) >= 1
    text_events = [json.loads(d) for d in data_lines if "text" in json.loads(d)]
    full_text = "".join(e["text"] for e in text_events)
    assert "general finance" in full_text

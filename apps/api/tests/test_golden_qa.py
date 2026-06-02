"""Golden Q&A tests — validate answer quality against known investor questions.

These tests make real Anthropic + tool API calls and are auto-skipped when
ANTHROPIC_API_KEY is not set. Run manually before releases:

    cd apps/api && python -m pytest tests/test_golden_qa.py -v -s
"""
import re

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

pytestmark = pytest.mark.skipif(
    not settings.anthropic_api_key,
    reason="needs ANTHROPIC_API_KEY",
)

_client = TestClient(app)


def _ask(question: str, ticker: str | None = None) -> str:
    resp = _client.post(
        "/chat",
        json={"message": question, "ticker": ticker},
    )
    assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text[:200]}"
    return resp.json()["reply"]


def test_apple_8k_filing():
    """Agent must reference an 8-K filing — not a vague refusal."""
    reply = _ask("Did Apple file a material 8-K in the last 90 days?", ticker="AAPL")
    assert reply, "Reply must not be empty"
    lower = reply.lower()
    assert "i don't know" not in lower, "Agent must not give a vague non-answer"
    assert "8-k" in lower or "8k" in lower or "filing" in lower, (
        f"Reply must reference an 8-K filing. Got:\n{reply[:400]}"
    )


def test_nvda_eps_four_quarters():
    """Agent must return multiple EPS figures — not a one-liner."""
    reply = _ask("What were NVDA's last 4 quarters EPS vs estimates?", ticker="NVDA")
    assert reply, "Reply must not be empty"
    assert len(reply) > 80, f"Reply too short to contain 4 quarters of data:\n{reply}"
    # Match dollar-prefixed decimals or plain decimals (e.g. $5.12 or 5.12) — avoids years/noise
    decimals = re.findall(r"\$?\d+\.\d{1,4}", reply)
    assert len(decimals) >= 2, (
        f"Reply must contain at least 2 EPS decimal values. Found {decimals}.\nReply:\n{reply[:400]}"
    )


def test_google_stock_price():
    """Agent must include a price — not just 'unavailable' with no context."""
    reply = _ask("What is Google's current stock price?", ticker="GOOGL")
    assert reply, "Reply must not be empty"
    lower = reply.lower()
    has_price = "$" in reply or bool(re.search(r"\d{3,4}\.\d{2}", reply))
    assert has_price, (
        f"Reply must contain a price value (e.g. $185.23). Got:\n{reply[:400]}"
    )


def test_buy_apple_disclaimer():
    """Agent must include a disclaimer and must NOT give a direct buy/sell call."""
    reply = _ask("Should I buy Apple stock?", ticker="AAPL")
    assert reply, "Reply must not be empty"
    lower = reply.lower()
    has_disclaimer = any(
        phrase in lower
        for phrase in ("not investment advice", "not financial advice", "not a financial advisor", "disclaimer")
    )
    assert has_disclaimer, f"Reply must include a disclaimer. Got:\n{reply[:400]}"
    forbidden = (
        "you should buy",
        "i recommend buying",
        "i recommend selling",
        "you should sell",
    )
    for phrase in forbidden:
        assert phrase not in lower, (
            f"Reply must not contain direct recommendation '{phrase}'.\nGot:\n{reply[:400]}"
        )

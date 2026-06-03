"""Market data REST endpoints — thin wrappers over market_client MCP calls."""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.config import settings
from app.mcp import market_client

router = APIRouter(prefix="/market", tags=["market"])
log = logging.getLogger(__name__)


@router.get("/quote/{ticker}")
async def quote(ticker: str) -> dict[str, Any]:
    """Latest stock quote: price, change%, market cap, 52-week range."""
    if not settings.fmp_api_key:
        return {}
    try:
        result = await market_client.get_quote(ticker.upper(), api_key=settings.fmp_api_key)
        return result or {}
    except Exception as exc:
        log.warning("quote(%s) failed: %s", ticker, exc)
        return {}


@router.get("/earnings/{ticker}")
async def earnings(
    ticker: str,
    limit: int = Query(default=4, ge=1, le=8),
) -> list[dict[str, Any]]:
    """EPS actuals vs estimates for the last N quarters."""
    if not settings.fmp_api_key:
        return []
    try:
        result = await market_client.get_earnings_history(
            ticker.upper(), limit=limit, api_key=settings.fmp_api_key
        )
        return result or []
    except Exception as exc:
        log.warning("earnings(%s) failed: %s", ticker, exc)
        return []


@router.get("/calendar")
async def calendar(
    from_date: str | None = Query(default=None),
    to_date: str | None = Query(default=None),
) -> list[dict[str, Any]]:
    """Upcoming earnings events in a date range (default: today → +7 days)."""
    if not settings.fmp_api_key:
        return []
    today = date.today()
    fd = from_date or today.isoformat()
    td = to_date or (today + timedelta(days=7)).isoformat()
    try:
        date.fromisoformat(fd)
        date.fromisoformat(td)
    except ValueError:
        raise HTTPException(status_code=422, detail="from_date and to_date must be ISO format: YYYY-MM-DD")
    try:
        return await market_client.get_earnings_calendar(
            fd, td, api_key=settings.fmp_api_key
        )
    except Exception as exc:
        log.warning("calendar(%s→%s) failed: %s", fd, td, exc)
        return []


@router.get("/metrics/{ticker}")
async def metrics(ticker: str) -> dict[str, Any]:
    """Trailing-12-month key metrics: PE, PB, ROE, debt/equity."""
    if not settings.fmp_api_key:
        return {}
    try:
        result = await market_client.get_key_metrics_ttm(
            ticker.upper(), api_key=settings.fmp_api_key
        )
        return result or {}
    except Exception as exc:
        log.warning("metrics(%s) failed: %s", ticker, exc)
        return {}

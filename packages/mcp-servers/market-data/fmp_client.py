"""Async HTTP client for the Financial Modeling Prep (FMP) REST API."""
from __future__ import annotations

import asyncio
from datetime import date as _date
from typing import Any

import httpx

_FMP_BASE = "https://financialmodelingprep.com/api/v3"

# FMP free tier: 250 req/day — 3 concurrent keeps burst safe
_MAX_CONCURRENT = 3


class FMPClient:
    """
    Async client for FMP endpoints:
      - /quote/{ticker}                       → real-time quote
      - /historical/earning_calendar/{ticker} → historical EPS with surprise
      - /earning_calendar                     → upcoming earnings
      - /key-metrics-ttm/{ticker}             → trailing-12-month metrics
    """

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("FMPClient requires a non-empty api_key")
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={"Accept": "application/json"},
        )
        # Semaphore created lazily so it always binds to the active event loop
        self._sem: asyncio.Semaphore | None = None

    def _get_sem(self) -> asyncio.Semaphore:
        if self._sem is None:
            self._sem = asyncio.Semaphore(_MAX_CONCURRENT)
        return self._sem

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "FMPClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """GET with rate-limit semaphore and retry on 429 / 503.

        Makes up to 4 attempts with exponential backoff (1 s, 2 s, 4 s between
        retries). Does not sleep after the final attempt.
        Raises ValueError on FMP application-level errors (HTTP 200 with
        {"Error Message": "..."} body).
        """
        merged = {**(params or {}), "apikey": self._api_key}
        url = f"{_FMP_BASE}{path}"

        async with self._get_sem():
            for attempt in range(4):
                resp = await self._client.get(url, params=merged)
                if resp.status_code in (429, 503):
                    if attempt < 3:
                        await asyncio.sleep(2 ** attempt)   # 1 s, 2 s, 4 s
                    continue
                resp.raise_for_status()
                data = resp.json()
                # FMP returns HTTP 200 with {"Error Message": "..."} for bad
                # keys, quota exhaustion, or unknown tickers
                if isinstance(data, dict) and "Error Message" in data:
                    raise ValueError(data["Error Message"])
                return data
            resp.raise_for_status()
            return resp.json()  # unreachable; satisfies type checker

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    async def get_quote(self, ticker: str) -> dict[str, Any] | None:
        """Return real-time quote for *ticker*, or None if not found."""
        data = await self._get(f"/quote/{ticker.upper()}")
        if isinstance(data, list) and data:
            return data[0]
        return None

    async def get_earnings_history(
        self,
        ticker: str,
        limit: int = 4,
    ) -> list[dict[str, Any]]:
        """
        Return historical EPS actuals vs estimates for *ticker*.

        Adds ``surprisePct`` = (actual − estimate) / |estimate| × 100
        to each record. Records without both values get ``surprisePct = None``.
        Slices to *limit* before computing surprise to avoid wasted work.
        """
        data = await self._get(f"/historical/earning_calendar/{ticker.upper()}")

        # FMP v3 returns a list directly; some versions wrap in {"historical": [...]}
        if isinstance(data, list):
            records = data[:limit]
        elif isinstance(data, dict):
            records = data.get("historical", [])[:limit]
        else:
            records = []

        for entry in records:
            actual = entry.get("eps")
            estimated = entry.get("epsEstimated")
            if actual is not None and estimated is not None and estimated != 0:
                entry["surprisePct"] = round(
                    (actual - estimated) / abs(estimated) * 100, 2
                )
            else:
                entry["surprisePct"] = None

        return records

    async def get_earnings_calendar(
        self,
        from_date: str,
        to_date: str,
    ) -> list[dict[str, Any]]:
        """
        Return upcoming earnings announcements between *from_date* and *to_date*.

        Dates must be in YYYY-MM-DD format. Raises ValueError on invalid format.
        """
        # Guard against malformed dates from LLM tool calls
        try:
            _date.fromisoformat(from_date)
            _date.fromisoformat(to_date)
        except ValueError as exc:
            raise ValueError(
                f"Dates must be in YYYY-MM-DD format, got {from_date!r} / {to_date!r}"
            ) from exc

        data = await self._get(
            "/earning_calendar",
            params={"from": from_date, "to": to_date},
        )
        return data if isinstance(data, list) else []

    async def get_key_metrics_ttm(self, ticker: str) -> dict[str, Any] | None:
        """Return trailing-12-month key metrics for *ticker*, or None."""
        data = await self._get(f"/key-metrics-ttm/{ticker.upper()}")
        if isinstance(data, list) and data:
            return data[0]
        return None

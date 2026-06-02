"""Async HTTP client for the Financial Modeling Prep (FMP) REST API."""
from __future__ import annotations

import asyncio
from datetime import date as _date
from typing import Any

import httpx

# FMP stable API (replaces legacy /api/v3/ — dropped Aug 2025 for new accounts)
_FMP_BASE = "https://financialmodelingprep.com/stable"

# FMP free tier: 250 req/day — 3 concurrent keeps burst safe
_MAX_CONCURRENT = 3


class FMPClient:
    """
    Async client for FMP stable endpoints:
      - /quote                   → real-time quote (symbol query param)
      - /earnings                → historical EPS with surprise (symbol query param)
      - /earnings-calendar       → upcoming earnings (client-side date filter)
      - /key-metrics-ttm         → trailing-12-month metrics (symbol query param)
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
        resp: httpx.Response | None = None  # explicit init — avoids unbound ref on early error

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
        """Return real-time quote for *ticker*, or None if not found.

        Uses the stable /quote endpoint (symbol as query param).
        Adds backward-compat aliases so callers reading old v3 field names work:
          changePercentage  → also exposed as changesPercentage
          pe / eps          → None (not in stable free tier)
        """
        data = await self._get("/quote", params={"symbol": ticker.upper()})
        if isinstance(data, list) and data:
            record = data[0]
            # backward-compat: old callers read 'changesPercentage'
            record.setdefault("changesPercentage", record.get("changePercentage"))
            record.setdefault("pe", None)   # not in stable free tier
            record.setdefault("eps", None)  # not in stable free tier
            return record
        return None

    async def get_earnings_history(
        self,
        ticker: str,
        limit: int = 4,
    ) -> list[dict[str, Any]]:
        """Return historical EPS actuals vs estimates for *ticker*.

        Uses the stable /earnings endpoint (symbol as query param).
        Free tier caps at 5 records per request. The endpoint returns both
        past and future quarters; future quarters have epsActual=null and are
        filtered out so only historical records are returned.

        Adds backward-compat aliases:
          epsActual  → also exposed as eps
          surprisePct = (epsActual - epsEstimated) / |epsEstimated| * 100
        """
        # Always request 5 (free-tier max); filter historical below
        data = await self._get("/earnings", params={"symbol": ticker.upper(), "limit": 5})

        if isinstance(data, list):
            # Filter future quarters (epsActual=None), then slice to requested limit
            records = [r for r in data if r.get("epsActual") is not None][:limit]
        else:
            records = []

        for entry in records:
            entry["eps"] = entry.get("epsActual")  # unconditional alias — authoritative
            actual = entry.get("epsActual")
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
        """Return upcoming earnings announcements between *from_date* and *to_date*.

        Dates must be in YYYY-MM-DD format. Raises ValueError on invalid format.

        Note: the stable free tier does not support from/to query params (402)
        and only returns recent past earnings (~90 days back). Upcoming quarters
        are not available on the free tier. This method fetches the full calendar
        and filters client-side so the interface stays consistent.
        """
        try:
            _date.fromisoformat(from_date)
            _date.fromisoformat(to_date)
        except ValueError as exc:
            raise ValueError(
                f"Dates must be in YYYY-MM-DD format, got {from_date!r} / {to_date!r}"
            ) from exc

        # Free tier: no date range params, past ~90 days only — filter client-side
        data = await self._get("/earnings-calendar")
        if not isinstance(data, list):
            return []

        result = []
        for r in data:
            date_str = r.get("date", "")
            if not date_str:
                continue
            try:
                # Validate ISO format before lexicographic comparison
                _date.fromisoformat(date_str)
            except ValueError:
                continue
            if from_date <= date_str <= to_date:
                result.append(r)
        return result

    async def get_key_metrics_ttm(self, ticker: str) -> dict[str, Any] | None:
        """Return trailing-12-month key metrics for *ticker*, or None.

        Uses the stable /key-metrics-ttm endpoint (symbol as query param).
        Adds backward-compat aliases for old v3 field names:
          returnOnEquityTTM  → also exposed as roeTTM
          evToSalesTTM       → also exposed as priceToSalesRatioTTM
          netDebtToEBITDATTM → also exposed as debtToEquityTTM
          peRatioTTM, pbRatioTTM, revenuePerShareTTM, netIncomePerShareTTM → None
        """
        data = await self._get("/key-metrics-ttm", params={"symbol": ticker.upper()})
        if isinstance(data, list) and data:
            record = data[0]
            # backward-compat aliases for callers using old v3 field names
            record.setdefault("roeTTM", record.get("returnOnEquityTTM"))
            # evToSalesTTM is EV/Sales (not Price/Sales); exposed under both names
            record.setdefault("evToSalesTTM", record.get("evToSalesTTM"))
            record.setdefault("priceToSalesRatioTTM", record.get("evToSalesTTM"))
            # not available in stable free tier — set None so callers show "n/a"
            record.setdefault("debtToEquityTTM", None)   # netDebtToEBITDA ≠ D/E ratio
            record.setdefault("peRatioTTM", None)
            record.setdefault("pbRatioTTM", None)
            record.setdefault("revenuePerShareTTM", None)
            record.setdefault("netIncomePerShareTTM", None)
            return record
        return None

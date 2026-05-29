"""Ingest SEC filings for watchlist tickers into Qdrant.

Usage (from apps/api with venv active):
    python -m scripts.ingest_watchlist            # AAPL + GOOGL (default)
    python -m scripts.ingest_watchlist AAPL MSFT  # specific tickers
    python -m scripts.ingest_watchlist --all       # full 9-ticker watchlist
"""
from __future__ import annotations

import asyncio
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")


async def main(tickers: list[str]) -> None:
    from app.config import settings
    from app.rag.ingest import ingest_tickers

    if not settings.sec_edgar_user_agent or "@" not in settings.sec_edgar_user_agent:
        sys.exit(
            "ERROR: SEC_EDGAR_USER_AGENT must be set in .env as 'Name email@domain.com'. "
            "EDGAR blocks requests without a valid User-Agent."
        )

    logging.getLogger("httpx").setLevel(logging.WARNING)
    await ingest_tickers(
        tickers=tickers,
        qdrant_url=settings.qdrant_url,
        user_agent=settings.sec_edgar_user_agent,
    )
    logging.info("Done.")


if __name__ == "__main__":
    args = sys.argv[1:]

    if "--all" in args:
        from app.config import settings
        chosen = settings.default_watchlist
    elif args:
        chosen = [t.upper() for t in args if not t.startswith("-")]
    else:
        # Default: start with just AAPL + GOOGL so the first run is fast
        chosen = ["AAPL", "GOOGL"]

    asyncio.run(main(chosen))

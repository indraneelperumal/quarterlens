"""Phase 1 smoke test — verify all components work end-to-end.

Usage (from apps/api with venv active):
    python -m scripts.smoke_test

Prints [PASS] / [FAIL] / [SKIP] for each check. Exits 1 if any FAIL.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Resolve apps/api so that `app.*` imports work when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.mcp import client as mcp_client  # noqa: E402
from app.rag.embedder import embed_texts  # noqa: E402
from app.rag.store import VectorStore  # noqa: E402

_GREEN = "\033[92m"
_RED = "\033[91m"
_YELLOW = "\033[93m"
_RESET = "\033[0m"

_results: list[tuple[str, str, bool | None]] = []  # (label, message, passed|None=skip)


def _log(label: str, passed: bool | None, message: str) -> None:
    _results.append((label, message, passed))
    if passed is True:
        tag = f"{_GREEN}[PASS]{_RESET}"
    elif passed is False:
        tag = f"{_RED}[FAIL]{_RESET}"
    else:
        tag = f"{_YELLOW}[SKIP]{_RESET}"
    print(f"  {tag}  {label}: {message}")


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def _check_qdrant_reachable(url: str) -> bool:
    try:
        store = VectorStore(url)
        store._client.get_collections()
        _log("Qdrant reachable", True, f"connected to {url}")
        return True
    except Exception as exc:
        _log("Qdrant reachable", False, str(exc))
        return False


def _check_qdrant_has_data(url: str) -> bool:
    try:
        store = VectorStore(url)
        n = store.count()
        if n == 0:
            _log("Qdrant has data", False, "collection is empty — run ingest_watchlist.py first")
            return False
        _log("Qdrant has data", True, f"{n} points in collection")
        return True
    except Exception as exc:
        msg = str(exc)
        if "doesn't exist" in msg or "Not found" in msg:
            _log("Qdrant has data", False, "financial_docs collection missing — run ingest_watchlist.py first")
        else:
            _log("Qdrant has data", False, msg)
        return False


async def _check_mcp_recent_filings(user_agent: str) -> None:
    try:
        filings = await asyncio.wait_for(
            mcp_client.recent_filings("AAPL", "8-K", limit=10, user_agent=user_agent),
            timeout=60.0,
        )
        if not filings:
            _log("MCP recent_filings", False, "returned empty list")
            return
        most_recent = filings[0]["date"]
        _log("MCP recent_filings", True, f"{len(filings)} filings returned (most recent: {most_recent})")
    except asyncio.TimeoutError:
        _log("MCP recent_filings", False, "timed out after 60 s")
    except Exception as exc:
        _log("MCP recent_filings", False, str(exc))


async def _check_qdrant_search(url: str) -> None:
    try:
        query = "Apple 8-K material event disclosure"
        vec = embed_texts([query])[0]
        store = VectorStore(url)
        results = store.search(vec, limit=5, ticker="AAPL")
        if not results:
            _log("Qdrant search", False, "no results — run ingest_watchlist.py first")
            return
        top = results[0]
        _log(
            "Qdrant search",
            True,
            f"top hit score={top['score']:.3f}  date={top.get('date','?')}  form={top.get('form_type','?')}",
        )
    except Exception as exc:
        _log("Qdrant search", False, str(exc))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def _run_all() -> None:
    qdrant_up = _check_qdrant_reachable(settings.qdrant_url)

    has_data = False
    if qdrant_up:
        has_data = _check_qdrant_has_data(settings.qdrant_url)
    else:
        _log("Qdrant has data", None, "skipped — Qdrant unreachable")

    if has_data:
        await _check_qdrant_search(settings.qdrant_url)
    else:
        _log("Qdrant search", None, "skipped — no data in collection")

    await _check_mcp_recent_filings(settings.sec_edgar_user_agent)


def main() -> None:
    print("\nPhase 1 smoke test\n" + "─" * 40)
    asyncio.run(_run_all())

    failures = [r for r in _results if r[2] is False]
    print("─" * 40)
    if failures:
        print(f"\n{_RED}{len(failures)} check(s) failed.{_RESET}\n")
        sys.exit(1)
    else:
        skips = [r for r in _results if r[2] is None]
        if skips:
            print(f"\n{_YELLOW}All checks passed ({len(skips)} skipped).{_RESET}\n")
        else:
            print(f"\n{_GREEN}All checks passed.{_RESET}\n")


if __name__ == "__main__":
    main()

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from functools import partial

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.config import settings
from app.mcp import client as mcp_client
from app.rag.embedder import embed_texts
from app.rag.store import VectorStore

router = APIRouter(prefix="/chat", tags=["chat"])
log = logging.getLogger(__name__)


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


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Phase 1: MCP filing lookup + Qdrant RAG. Claude synthesis added in Phase 3."""

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

    # ── 2. MCP: recent 8-K filings filtered to last 90 days ────────────────
    filings: list[dict] = []
    mcp_error: str | None = None
    cutoff = (date.today() - timedelta(days=90)).isoformat()

    try:
        raw = await mcp_client.recent_filings(
            ticker, "8-K", limit=10, user_agent=settings.sec_edgar_user_agent
        )
        # Explicit None guard — ISO YYYY-MM-DD sorts lexicographically
        filings = [f for f in raw if f.get("date") and f["date"] >= cutoff]
    except Exception as exc:
        mcp_error = str(exc)

    # ── 3. Qdrant: semantic search (CPU-bound encode runs in thread pool) ───
    chunks: list[dict] = []
    qdrant_error: str | None = None

    try:
        loop = asyncio.get_event_loop()
        vec = await loop.run_in_executor(None, partial(embed_texts, [request.message]))
        vec = vec[0]
        store = VectorStore(settings.qdrant_url)
        store.ensure_collection()
        chunks = store.search(vec, limit=5, ticker=ticker, form_type="8-K")
    except Exception as exc:
        qdrant_error = str(exc)

    # ── 4. Format reply ─────────────────────────────────────────────────────
    lines: list[str] = []

    if filings:
        lines.append(f"{ticker} filed {len(filings)} 8-K(s) in the last 90 days:\n")
        for f in filings:
            desc = f.get("description") or f["accession_number"]
            lines.append(f"  • {f['date']}  {desc}")
    elif mcp_error:
        lines.append(f"Could not fetch filings from EDGAR: {mcp_error}")
    else:
        lines.append(f"No 8-K filings found for {ticker} in the last 90 days.")

    if chunks:
        lines.append(f"Related context from ingested filings ({len(chunks)} chunk(s)):")
        for c in chunks[:3]:
            snippet = c.get("text", "")[:200].replace("\n", " ")
            lines.append(f"  [{c.get('date', '?')}] {snippet}…")
    elif qdrant_error:
        lines.append(f"(Vector search unavailable: {qdrant_error})")

    # ── 5. Build sources from filings + any unique chunk accessions ─────────
    sources: list[dict] = [
        {
            "accession_number": f["accession_number"],
            "date": f["date"],
            "form": f.get("form", "8-K"),
        }
        for f in filings
    ]
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

    return ChatResponse(reply="\n".join(lines), sources=sources)

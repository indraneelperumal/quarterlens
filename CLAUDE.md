# CLAUDE.md — MCP Earnings Intelligence Agent

Comprehensive spec, workflow rules, and lessons learned for every Claude Code session working in this repo.

---

## Session workflow (mandatory)

1. **Read this file + CONTINUATION.md** before any implementation.
2. **Enter plan mode** (`/plan`) and get explicit user approval before starting any step.
3. **Implement one step at a time** — never skip steps or batch multiple steps.
4. **Run a review subagent** after every implementation step. Apply all critical/important fixes before committing.
5. **`git add` + `git commit`** after each reviewed and fixed step. The agent commits; the user pushes.

### Git rules (non-negotiable)
- NEVER run `git push`.
- NEVER include "Co-Authored-By", "Co-authored-by", or any Claude/Anthropic attribution in commit messages.
- Commit message format: `Phase N step M: short description` (e.g., `Phase 2 step 1: FMP async HTTP client`).
- Stage only relevant files — never `git add -A` blindly.

---

## Architecture overview

```
┌─────────────────────────────────────────────────┐
│            Next.js Frontend (:3000)             │
│   Chat interface  │  Earnings dashboard (P5+)  │
└──────────────────────────┬──────────────────────┘
                           │ HTTP (JSON)
┌──────────────────────────▼──────────────────────┐
│         Python FastAPI Backend (:8000)          │
│  MCP Client (stdio)  │  RAG Pipeline (Qdrant)  │
│  asyncio.gather — all sources concurrent        │
│  Anthropic Claude (Phase 3+)                    │
└──────────┬──────────────────────────────────────┘
           │ MCP stdio
    ┌──────┴─────────────┐
    │  SEC EDGAR server  │   market-data server
    │  (sec-edgar/)      │   (market-data/)
    └────────────────────┘
                  │
         Qdrant (:6333) — collection: financial_docs
```

### Repo layout

| Path | Role |
|------|------|
| `apps/web` | Next.js 16 App Router — chat UI |
| `apps/api` | FastAPI host — MCP client, RAG, Claude orchestration |
| `packages/mcp-servers/sec-edgar` | SEC EDGAR FastMCP server |
| `packages/mcp-servers/market-data` | FMP market-data FastMCP server |

### Stack (locked — do not change without plan approval)

| Layer | Choice | Notes |
|-------|--------|-------|
| UI | Next.js 16 (App Router) | Tailwind, `"use client"` for chat shell |
| API | FastAPI (Python 3.10+) | async routes, Pydantic v2 |
| LLM | Anthropic Claude | Haiku for ticker extraction; Sonnet/Opus for synthesis (Phase 3) |
| Vector DB | Qdrant (Docker, local :6333) | Collection `financial_docs`, 384-dim cosine |
| Embeddings | sentence-transformers `all-MiniLM-L6-v2` | Local, no API cost, lazy-loaded via `@lru_cache` |
| Market data | FMP (primary) + Alpha Vantage (sentiment) | Free tier; 250 req/day FMP |
| News | Tavily (real-time search) | Direct async REST — no Node.js MCP dependency |
| SEC filings | EDGAR (no key; User-Agent required) | Custom MCP server |

---

## Code patterns and conventions

### MCP servers (FastMCP)

Follow `packages/mcp-servers/sec-edgar/server.py` exactly:
- `mcp = FastMCP("server-name")`
- `_API_KEY = os.getenv("KEY_NAME", "")` at module level
- Guard at top of every tool: `if not _API_KEY: return "ERROR: KEY_NAME not set"`
- Return JSON strings on success, `"ERROR: <message>"` on failure — never raise from tools
- Single module-level client instance; handle missing key gracefully (no instantiation if key is empty)

### MCP clients (FastAPI side)

Follow `apps/api/app/mcp/client.py` exactly:
- Spawn server via `StdioServerParameters` per call (no persistent process)
- `await session.initialize()`
- Call `sec_tool(session, "tool_name", {...})` or equivalent wrapper
- Check `result.isError` first, then `text.startswith("ERROR:")` — raise `RuntimeError` with clean message
- Parse JSON from tool result text

### HTTP clients (httpx async)

Follow `packages/mcp-servers/market-data/fmp_client.py`:
- `httpx.AsyncClient(timeout=30.0, follow_redirects=True)`
- Semaphore created **lazily** (not in `__init__`) — avoids event loop binding issues
- Retry loop: `for attempt in range(4)` — sleep `2**attempt` only if `attempt < 3`
- FMP 200-error detection: check `isinstance(data, dict) and "Error Message" in data`
- Always slice data **before** computing derived fields (e.g., surprisePct)

### RAG pipeline

- Chunk size: 1500 chars, overlap: 200 chars (guard: `if overlap >= chunk_size: raise ValueError`)
- Embeddings: `normalize_embeddings=True` (cosine-compatible)
- IDs: `uuid5(NAMESPACE_URL, f"{accession}#{chunk_index}")` — deterministic, idempotent re-ingestion
- Qdrant upsert: use `query_points()` NOT `.search()` (removed in qdrant-client 1.12+)
  ```python
  result = self._client.query_points(
      collection_name=COLLECTION, query=vector, limit=limit,
      query_filter=Filter(must=must) if must else None, with_payload=True,
  )
  return [{**(hit.payload or {}), "score": hit.score} for hit in result.points]
  ```

### Chat route (apps/api/app/routes/chat.py)

- Ticker resolution order: **message extraction FIRST** (via Haiku), hint as fallback
- CPU-bound embedding must use `run_in_executor` — never block the event loop
- Call `store.ensure_collection()` before search — first-run safe
- Date filter guard: `f.get("date") and f["date"] >= cutoff` (None-safe ISO string sort)
- All external calls (MCP, Qdrant, Claude) wrapped in `try/except` for graceful degradation
- Phase 2+: use `asyncio.gather(*all_coros, return_exceptions=True)` — all sources concurrent

### Config (apps/api/app/config.py)

- Loads from monorepo root `.env` via `Path(__file__).resolve().parents[3]`
- All keys default to `""` — feature-gate on truthiness (`if settings.fmp_api_key:`)
- Adding a new key: add to `Settings` class with `str = ""` default

### Tests

- Use `pytest.mark.skipif` at **module level** for integration tests that need API keys
- Use **function-scoped** fixtures (not session-scoped) when `pytest.skip()` is called inside — session-scoped skip aborts entire suite
- Async tests via `pytest-anyio` or `asyncio.wait_for(..., timeout=60.0)` for MCP calls
- Never mock at the infrastructure level (Qdrant, EDGAR) — bugs hide in the gap

### Next.js (apps/web)

- Read `apps/web/AGENTS.md` → `apps/web/node_modules/next/dist/docs/` before touching any Next.js code
- Chat UI: `"use client"` component, `useState` for messages, loading, ticker
- Dropdown defaults to `value=""` (Auto-detect) — never a ticker — so message-level extraction takes priority
- Error display: show `err.detail` from API when available, not generic "Failed to fetch"

---

## Environment variables

| Variable | Required for | Default |
|----------|-------------|---------|
| `ANTHROPIC_API_KEY` | Ticker extraction (Phase 1) + synthesis (Phase 3) | `""` |
| `FMP_API_KEY` | Market data MCP (Phase 2) | `""` |
| `ALPHA_VANTAGE_API_KEY` | News sentiment (Phase 2) | `""` |
| `TAVILY_API_KEY` | News search (Phase 2) | `""` |
| `SEC_EDGAR_USER_AGENT` | SEC filings — REQUIRED format: `"Name email@domain.com"` | `"EarningsAgent contact@example.com"` |
| `QDRANT_URL` | Vector DB | `"http://localhost:6333"` |
| `NEXT_PUBLIC_API_URL` | Web → API (in `apps/web/.env.local`) | `"http://localhost:8000"` |

---

## Known bugs and fixes (do not re-introduce)

### Python / FastAPI

| Bug | Symptom | Fix |
|-----|---------|-----|
| `parents[5]` in ingest.py | `ModuleNotFoundError` for edgar package | `parents[4]` is monorepo root |
| Random UUID4 chunk IDs | Duplicate Qdrant points on re-ingest | `uuid5(NAMESPACE_URL, f"{accession}#{chunk_index}")` |
| `json.loads` on `"ERROR: ..."` string | `JSONDecodeError` in MCP client | Check `text.startswith("ERROR:")` before `json.loads` |
| Overlap ≥ chunk size | Infinite chunker loop | `ValueError` guard at top of `chunk_text` |
| `ensure_collection` TOCTOU | Race on startup creates duplicate collection | Wrap `create_collection` in try/except |
| Ticker stored lowercase | Qdrant filter misses docs | `ticker = ticker.upper()` at top of `ingest_ticker` |
| `QdrantClient.search()` removed | `AttributeError` at query time | Use `query_points()`, access `result.points` |
| Dropdown default AAPL | Dropdown overrides message ticker | Default to `""` (Auto-detect); extraction before hint |
| `test_qdrant_search` 404 | `UnexpectedResponse` on missing collection | Wrap `count()` in try/except, call `pytest.skip()` |
| `embed_texts` blocking event loop | Slow responses under load | `loop.run_in_executor(None, partial(embed_texts, [...]))` |
| Session-scoped fixture + skip | Single skip kills entire test session | Switch to function-scoped fixture |
| FMP retry sleeps after last attempt | Wastes 4s on final failure | `if attempt < 3: await asyncio.sleep(...)` |
| FMP 200 `{"Error Message": "..."}` | Silent bad-key failures | Detect and raise `ValueError` in `_get` |
| Semaphore in `__init__` | Binds to wrong event loop pre-3.10 | Lazy init via `_get_sem()` method |
| `surprisePct` computed before slice | Wasted work on large histories | Slice to `limit` first, then compute |
| Wrong fallback key in FMP history | Empty list from some endpoints | `data.get("historical", [])` not `"historicalStockList"` |
| Date not validated in calendar | LLM passes bad format → cryptic error | `_date.fromisoformat()` guard at entry |

### Infrastructure

| Bug | Symptom | Fix |
|-----|---------|-----|
| Uvicorn reload loop | Terminal floods with `.venv/...` changes | `--reload-dir app` only |
| Root `.env` not loaded | API keys ignored | Load from `parents[3]` (monorepo root) |
| Qdrant healthcheck fails | No `curl` in official image | Bash TCP probe on `/readyz` |
| `apps/web/.env.example` gitignored | Clean clone can't set `NEXT_PUBLIC_API_URL` | Narrow ignore to `.env.local` only |
| Requires Python 3.12 | Fails on macOS 3.10 default | `requires-python = ">=3.10"` |

---

## Phase status

| Phase | Deliverable | Status |
|-------|-------------|--------|
| **0** | Monorepo, Qdrant compose, FastAPI skeleton, Next.js chat shell | Done |
| **1** | SEC EDGAR MCP + RAG ingest + Qdrant + chat route (Phase 1 format) | Done |
| **2** | FMP MCP + Tavily + Alpha Vantage + parallel gather in chat | In progress — Step 1 done |
| **3** | Claude agent loop (tool_use, streaming SSE) | Pending |
| **4** | Golden Q&A tests + investor response schema | Pending |
| **5** | Chat UI citations panel + SSE | Pending |
| **6** | Earnings dashboard (surprises, guidance trends) | Pending |

### Phase 2 step status

| Step | File(s) | Status |
|------|---------|--------|
| 1 | `packages/mcp-servers/market-data/fmp_client.py` + `requirements.txt` | Done, committed |
| 2 | `packages/mcp-servers/market-data/server.py` | Next |
| 3 | `apps/api/app/mcp/market_client.py` + update `config.py` (add `tavily_api_key`) | Pending |
| 4 | `apps/api/app/mcp/news.py` (Tavily + Alpha Vantage REST) | Pending |
| 5 | Update `apps/api/app/routes/chat.py` (parallel gather) + `tests/test_market_client.py` | Pending |

---

## Running the project

```bash
# 1. Start Qdrant
docker compose up -d

# 2. API (Terminal 1)
cd apps/api
source .venv/bin/activate
uvicorn app.main:app --reload --reload-dir app --port 8000

# 3. Web (Terminal 2)
cd apps/web
npm run dev

# 4. Ingest filings (one-time per ticker)
cd apps/api && source .venv/bin/activate
python -c "import asyncio; from app.rag.ingest import ingest_ticker; asyncio.run(ingest_ticker('AAPL'))"

# 5. Run tests
cd apps/api && pytest -q
```

## Valid endpoints

| URL | Method | Purpose |
|-----|--------|---------|
| `http://localhost:3000` | GET | Chat UI |
| `http://localhost:8000/health` | GET | Health + watchlist |
| `http://localhost:8000/docs` | GET | Swagger |
| `http://localhost:8000/chat` | POST | `{"message": "...", "ticker": "AAPL"}` |
| `http://localhost:6333` | GET | Qdrant dashboard |

---

## Product goal

MCP-powered earnings intelligence for **retail investors** managing their own portfolio.

**MVP answer quality target:** Numbers + conversational context, grounded in filings and live market data, with citations and a disclaimer.

**Golden questions:**
- "Did Apple invest in anything recently that could impact my portfolio?"
- "Google last 4 quarters: proposed plan vs actual results?"
- "Nvidia recent 8-Ks — any material events I should know about?"

**Scope (v0):** No broker integration, no options, no full S&P 500, no push notifications, no multi-user auth.

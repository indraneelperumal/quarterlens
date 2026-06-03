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
│   Chat interface  │  Earnings dashboard (/P7)  │
└──────────────────────────┬──────────────────────┘
                           │ HTTP / SSE
┌──────────────────────────▼──────────────────────┐
│         Python FastAPI Backend (:8000)          │
│  routes/chat.py  │  routes/market.py            │
│  agent/loop.py (Claude Sonnet tool_use loop)    │
│  MCP clients (stdio) │ RAG Pipeline (Qdrant)    │
│  asyncio.gather — all tool calls concurrent     │
└──────────┬──────────────────────────────────────┘
           │ MCP stdio
    ┌──────┴─────────────┐
    │  SEC EDGAR server  │   market-data server
    │  (sec-edgar/)      │   (market-data/) → FMP /stable
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
| LLM | Anthropic Claude | Sonnet for agent synthesis; Haiku only in Phase 2 fallback ticker extraction |
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

- Chunk size: 1500 chars, overlap: **300 chars** (increased from 200 for better cross-chunk continuity)
- Chunker snaps to the nearest paragraph/sentence boundary before each hard cut via `_snap_to_boundary()` — prevents splitting mid-sentence. Lookback window: 250 chars.
- Always `break` when `end >= len(text)` — do NOT use `max(step, 1)` advance or the loop will re-emit chunks 1 char at a time for short texts.
- Embeddings: `normalize_embeddings=True` (cosine-compatible); bi-encoder model `all-MiniLM-L6-v2`, effective window ~256 tokens (~960 chars).
- IDs: `uuid5(NAMESPACE_URL, f"{accession}#{chunk_index}")` — deterministic, idempotent re-ingestion.
- Qdrant upsert: use `query_points()` NOT `.search()` (removed in qdrant-client 1.12+).
  ```python
  result = self._client.query_points(
      collection_name=COLLECTION, query=vector, limit=limit,
      query_filter=Filter(must=must) if must else None, with_payload=True,
  )
  return [{**(hit.payload or {}), "score": hit.score} for hit in result.points]
  ```
- **Two-stage retrieval** — do not collapse back to single-stage:
  1. Bi-encoder (MiniLM) retrieves `limit=20` candidates from Qdrant.
  2. Cross-encoder (`cross-encoder/ms-marco-MiniLM-L-6-v2`) scores each query×chunk pair and keeps top 5.
  3. Both models are lazy-loaded via `@lru_cache(maxsize=1)` in `embedder.py`.
  4. Re-ranker runs in `run_in_executor` (same as embedder) — never block the async loop.
  ```python
  docs = await loop.run_in_executor(None, partial(_qdrant_search, vec[0], ticker))
  if len(docs) > 1:
      docs = await loop.run_in_executor(None, partial(rerank, query, docs, 5))
  ```
- **Re-ingest required** whenever `CHUNK_SIZE` or `CHUNK_OVERLAP` changes — old chunks stay in Qdrant with their original UUIDs and will be served alongside new chunks until the collection is cleared.

### Chat route (apps/api/app/routes/chat.py)

- **Phase 3+ (agent active):** `_resolve_ticker` returns only the UI hint (or None) — no Haiku call. Claude identifies tickers itself via tool calls.
- **Phase 2 fallback:** `_resolve_ticker` uses Haiku extraction → hint → None. Only reached when `ANTHROPIC_API_KEY` is unset.
- Agent path: no hard ticker gate — agent handles ticker=None gracefully (e.g. general finance questions)
- `ChatRequest` includes `history: list[HistoryMessage]` for multi-turn context passed to `run_agent`
- `run_agent` returns `tuple[str, list[Citation]]` — unpack as `reply, citations = await run_agent(...)`
- `POST /chat` returns `InvestorResponse` (answer, citations, key_numbers, sentiment, disclaimer)
- `POST /chat/stream` word-by-word streams text chunks then sends `{"citations": [...]}` event before `[DONE]`
- CPU-bound embedding must use `asyncio.get_running_loop().run_in_executor()` — never `get_event_loop()` (deprecated in 3.10+)
- All external calls (MCP, Qdrant, Claude) wrapped in `try/except` for graceful degradation
- Phase 2+: use `asyncio.gather(*all_coros, return_exceptions=True)` — all sources concurrent

### Agent loop (apps/api/app/agent/loop.py)

- **Prompt caching** — system prompt and tool definitions are cached at Anthropic (ephemeral, 5-min TTL).
  Do NOT revert to passing `system=SYSTEM_PROMPT` (string) — it must stay as the list form:
  ```python
  _SYSTEM_BLOCK = [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]
  _CACHED_TOOLS = copy.deepcopy(TOOL_DEFINITIONS)
  _CACHED_TOOLS[-1] = {**_CACHED_TOOLS[-1], "cache_control": {"type": "ephemeral"}}
  ```
  Both are built once at module load and reused on every `ac.messages.create()` call.
- History passed in from `chat.py` is already text-only (the frontend never stores tool_use/tool_result blocks). No stripping needed in `run_agent`.
- The forced final synthesis call (when rounds exhausted) also uses `_SYSTEM_BLOCK` and `_CACHED_TOOLS` with `tool_choice={"type": "none"}` — the test checks for this kwarg.

### Config (apps/api/app/config.py)

- Loads from monorepo root `.env` via `Path(__file__).resolve().parents[3]`
- All keys default to `""` — feature-gate on truthiness (`if settings.fmp_api_key:`)
- Adding a new key: add to `Settings` class with `str = ""` default
- **Current token budget:** `claude_max_tokens=1024`, `claude_max_tool_rounds=3` — do not raise without a clear reason; most financial Q&A fits in ≤400 output tokens and ≤2 tool rounds

### Tool definitions (apps/api/app/agent/tools.py)

- `search_docs` must be the **first** tool in `TOOL_DEFINITIONS` — Claude uses list order as a recency/preference signal.
- Each description encodes when NOT to use the tool ("use ONLY when…", "avoid if search_docs answers it") — this is what actually controls routing; vague descriptions cause the model to over-call EDGAR.
- `get_filing_content` default `max_chars=3000` — do not raise above 4000; each 1000 chars ≈ 250 tokens in tool results sent back in context.
- Tool routing priority (cheapest → most expensive): `search_docs` → `get_stock_quote` / `get_earnings_history` → `search_news` / `get_news_sentiment` → `search_sec_filings` → `get_filing_content`.
- Never duplicate tool descriptions between the tool def and the system prompt — the system prompt routing ladder refers to tools by name; the descriptions carry the detail.

### Tests

- Use `pytest.mark.skipif` at **module level** for integration tests that need API keys
- Use **function-scoped** fixtures (not session-scoped) when `pytest.skip()` is called inside — session-scoped skip aborts entire suite
- Async tests via `pytest-anyio` or `asyncio.wait_for(..., timeout=60.0)` for MCP calls
- Never mock at the infrastructure level (Qdrant, EDGAR) — bugs hide in the gap

### Next.js (apps/web)

- Read `apps/web/AGENTS.md` → `apps/web/node_modules/next/dist/docs/` before touching any Next.js code
- Chat UI: `"use client"` component, `useState` for messages, loading, ticker
- Dropdown defaults to `value=""` (Auto-detect) — never a ticker — so agent identifies ticker via tools
- `history` is captured from `messages` state **before** the new user message is appended, then sent with every POST
- `MessageContent` renders `**bold**` and `\n` inline — no react-markdown or other deps
- SSE stream: consume `/chat/stream` with `res.body.getReader()`; split on `"\n\n"`; handle `{"text"}`, `{"citations"}`, `[DONE]` events
- Streaming bubble: append empty `{ role: "assistant", content: "", streaming: true }` immediately; append text chunks to it; set citations when the citations event arrives
- `CitationsPanel` / `SourceCard` in `apps/web/src/components/` — no new npm deps for chat
- Dashboard (`/dashboard`): `"use client"`, `useEffect` + `fetch` per section, separate loading state per card
- `recharts` added in Phase 7 (`npm install recharts`) — do not remove; used by `EarningsSurpriseChart`
- recharts `Tooltip.formatter` value type is `ValueType | undefined` — always guard with `typeof val === "number"` before calling `.toFixed()`
- Dashboard ticker selector defaults to first watchlist item (no Auto-detect) — all sections refetch on ticker change
- Calendar fetch is ticker-independent (global 7-day window) — lives in a separate `useEffect([], [])` that runs once

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
| FMP `/api/v3/` endpoints → 403 | All FMP market calls fail for post-Aug-2025 accounts | Migrate to `/stable/` base URL; query param `symbol=` not path param |
| `debtToEquityTTM` mapped to wrong field | `netDebtToEBITDA` ≠ D/E ratio (~0.3 vs ~1.5) | `setdefault("debtToEquityTTM", None)` — shows "n/a" honestly |
| `eps` alias used `setdefault` | If FMP returns `eps` field, alias silently uses wrong value | Unconditional `entry["eps"] = entry.get("epsActual")` |
| Tavily source shows raw URL | `source` field absent → full URL exposed in chat | `_domain_from_url()` via `urlparse` as fallback |
| Market cap shown as 13-digit int | `4498884016360` not human-readable | `_fmt_large()` → `$4.50T` / `$456B` / `$78M`; guards `nan`/`inf` |
| RFC 2822 date in news items | `"Thu, 28 May 2026 23:49:51 GMT"` shown verbatim | `_fmt_pub_date()` trims to `"28 May 2026"`; comma-presence guard |
| `_safe_json` → wrong form_type in search_docs | Hardcoded `form_type="8-K"` in `_qdrant_search` silently discards 10-K/10-Q | Pass `form_type=None` |
| `asyncio.get_event_loop()` in async context | Deprecated in 3.10+, raises in 3.12+ | Use `asyncio.get_running_loop()` inside `async def` |
| Agent max rounds exhausted → empty reply | All 5 rounds use tool_use; no text block produced | Forced final call with `tool_choice={"type": "none"}` after loop |
| Haiku pre-extraction adds latency | Separate API call before agent starts; ~700ms–1.5s wasted | Skip Haiku in agent path; agent identifies tickers via tools |
| Agent responses too long / report-style | Claude produces full tables and headers for simple questions | Explicit length rules in system prompt: 3–5 sentences for casual queries |
| No multi-turn memory | Every request starts fresh; agent repeats already-known context | `history: list[HistoryMessage]` field on `ChatRequest`; prepended to messages |
| Hard ticker gate blocked general questions | `"could not identify ticker"` error for non-ticker queries | Removed gate in agent path; agent responds to any message |
| Qdrant client version warning | `check_compatibility` warning on every startup | `QdrantClient(url=url, check_compatibility=False)` |
| `run_agent` returns bare string | No structured citations returned to caller | Change return to `tuple[str, list[Citation]]`; update all callers |
| `data["reply"]` in tests after Phase 6 | `KeyError` — field renamed to `answer` | `InvestorResponse.answer` — update test assertions and `_ask()` helper |
| Filing dict uses `"form"` not `"form_type"` | `extract_citations` misses form type on `search_sec_filings` results | Use `f.get("form_type") or f.get("form", "8-K")` |
| Streaming bubble not seeded immediately | Input disabled but no bubble appears until first chunk | Append `{role:"assistant",content:"",streaming:true}` before `fetch` call |
| `earnings` route returned raw `None` from FMP | `None` passed back as JSON — not an empty list | Added `or []` guard: `return result or []` |
| Calendar endpoint accepted arbitrary date strings | LLM could pass bad format → no validation before FMP call | `date.fromisoformat()` guard → `HTTPException(422)` |
| recharts `Tooltip` formatter typed `val: number` | TypeScript error — value is `ValueType \| undefined` | `typeof val === "number"` guard before `.toFixed()` |
| Chunker infinite loop on short text | `max(step, 1)` advances 1 char/iter when text < overlap | `break` when `end >= len(text)` — never rely on `max(step, 1)` alone |
| Bi-encoder retrieves 5 hard-cut candidates | Low precision; adjacent chunks miss the actual answer | Two-stage: fetch limit=20, re-rank with CrossEncoder, return top 5 |
| `search_sec_filings` called before `search_docs` | Live EDGAR hit for data already in local DB | `search_docs` listed first in `TOOL_DEFINITIONS`; "ALWAYS try first" in description |
| System prompt resent in full on every API call | ~700 tokens × N rounds per request | `cache_control: ephemeral` on `_SYSTEM_BLOCK` and `_CACHED_TOOLS[-1]` |
| `max_tokens=4096` allows report-length output | Claude produces tables and headers for simple Q | Reduced to 1024; enforces the brevity rule in the system prompt |
| `max_tool_rounds=5` allows runaway investigation | 5 consecutive EDGAR fetches on a complex query | Reduced to 3; forced final call handles the exhausted-rounds edge case |

### Infrastructure

| Bug | Symptom | Fix |
|-----|---------|-----|
| Uvicorn reload loop | Terminal floods with `.venv/...` changes | `--reload-dir app` only |
| Root `.env` not loaded | API keys ignored | Load from `parents[3]` (monorepo root) |
| Qdrant healthcheck fails | No `curl` in official image | Bash TCP probe on `/readyz` |
| `apps/web/.env.example` gitignored | Clean clone can't set `NEXT_PUBLIC_API_URL` | Narrow ignore to `.env.local` only |
| Requires Python 3.12 | Fails on macOS 3.10 default | `requires-python = ">=3.10"` |
| `pytest` without `python -m` | `ModuleNotFoundError: No module named 'app'` | Run as `python -m pytest` from inside `apps/api/` |

---

## Phase status

| Phase | Deliverable | Status |
|-------|-------------|--------|
| **0** | Monorepo, Qdrant compose, FastAPI skeleton, Next.js chat shell | Done |
| **1** | SEC EDGAR MCP + RAG ingest + Qdrant + chat route | Done |
| **2** | FMP MCP + Tavily + Alpha Vantage + parallel gather in chat | Done |
| **3** | Claude agent loop (tool_use, conversational, multi-turn, streaming SSE) | Done |
| **4** | Frontend: multi-turn history + markdown rendering in Next.js chat shell | Done |
| **5** | Golden Q&A tests + investor response schema | Done |
| **6** | Chat UI citations panel + SSE streaming | **Done** |
| **7** | Earnings dashboard (surprises, guidance trends) | **Done** |
| **8** | RAG optimisation — re-ranking, tool routing, prompt caching, token budget | **Done** |
| **9** | Deployment — Render (API) + Vercel (web) | **Done** |

### Phase 3 — complete

All steps committed to `main`.

| Step | Files | Notes |
|------|-------|-------|
| Part A polish | `news.py`, `chat.py`, `test_news.py` | `_domain_from_url`, `_fmt_large`, `_fmt_pub_date` |
| Step 1 | `config.py`, `agent/prompts.py`, `agent/tools.py` | 7 tool defs + executors + `safe_json` |
| Step 2 | `agent/loop.py`, `chat.py` | `run_agent()` loop, `/chat` wired, `/chat/stream` SSE |
| Step 3 | `tests/test_agent_loop.py` | 7 unit + integration tests |
| Conversational fix | `chat.py`, `agent/prompts.py` | History, no ticker gate, short responses |
| Latency fix | `chat.py`, `agent/prompts.py` | Skip Haiku pre-extraction in agent path |

### Phase 4 — complete

`apps/web/src/components/ChatShell.tsx` — one file, one commit.

- `history` captured before each submit and sent with every `POST /chat`
- `MessageContent` renders `**bold**` and `\n` — no new npm deps
- Animated bouncing dots loading indicator

### Phase 5 — complete

`apps/api/app/agent/schema.py` + `apps/api/tests/test_golden_qa.py` — two files, one commit.

- `Citation`, `KeyNumber`, `InvestorResponse` Pydantic models
- 4 golden Q&A tests (skipped without `ANTHROPIC_API_KEY`); all pass when key is set
- Disclaimer text: `"This is for research and education only. Not investment advice."`

### Phase 6 — complete

All steps committed to `main`. 58 tests passing.

| Step | Files | Notes |
|------|-------|-------|
| Step 1 | `agent/tools.py`, `agent/loop.py`, `routes/chat.py` | `extract_citations()`, `run_agent` → `tuple[str, list[Citation]]`, `/chat` returns `InvestorResponse`, `/chat/stream` word-by-word + citations event |
| Step 2 | `ChatShell.tsx`, `CitationsPanel.tsx`, `SourceCard.tsx` | SSE reader, streaming bubble, collapsible citations panel |
| Step 3 | `test_agent_loop.py`, `test_chat.py`, `test_golden_qa.py` | Updated for tuple return type and `InvestorResponse` shape |

### Phase 7 — complete

All steps committed to `main`. 67 tests passing.

| Step | Files | Notes |
|------|-------|-------|
| Step 1 | `routes/market.py`, `main.py`, `tests/test_market.py` | 4 `/market/*` endpoints; graceful no-key degradation; ISO date validation; 9 unit tests |
| Step 2 | `dashboard/page.tsx`, `EarningsSurpriseChart.tsx`, `EarningsCalendar.tsx`, `MetricsGrid.tsx`, `package.json` | recharts installed; EPS bar chart, 7-day calendar, 2×2 metrics grid |
| Step 3 | `ChatShell.tsx` | "Dashboard →" nav link in chat header |

### Phase 8 — complete

One commit to `main`. 67 tests passing.

| Step | Files | Notes |
|------|-------|-------|
| Step 1 | `chunker.py`, `embedder.py`, `store.py`, `tools.py`, `prompts.py`, `loop.py`, `config.py` | Paragraph snapping, cross-encoder re-ranker, RAG-first tool descriptions, prompt caching, token budget |

> After this commit, clear the Qdrant collection and re-ingest all tickers — old 1500-char hard-cut chunks will otherwise be served alongside new paragraph-snapped chunks.

### Phase 9 — complete

All steps committed to `main`. Project is live.

| Step | Files | Notes |
|------|-------|-------|
| Rebrand | `layout.tsx`, `ChatShell.tsx`, `main.py`, `health.py`, `config.py`, `server.py`, `pyproject.toml`, `test_root.py` | Renamed to QuarterLens; SEC_EDGAR_USER_AGENT → `QuarterLens indraneelr83@outlook.com` |
| Step 1 | `config.py`, `store.py`, `tools.py`, `chat.py`, `ingest.py`, `render.yaml`, `build.sh` | `qdrant_api_key` setting; Qdrant Cloud auth; CPU-only torch build; `render.yaml` at monorepo root |
| Ingest | Qdrant Cloud | 736 chunks across 9 tickers (AAPL/GOOGL/MSFT/NVDA/AMZN/JPM/UNH/XOM/COST) ingested into cloud collection |

**Render dashboard settings (render.yaml is NOT auto-read for dashboard-created services):**
- Root Directory: *(blank)*
- Build Command: `cd apps/api && bash build.sh`
- Start Command: `cd apps/api && uvicorn app.main:app --host 0.0.0.0 --port $PORT`

**Known infrastructure notes:**
- `render.yaml` is only auto-applied via Render Blueprint deploys; dashboard-created services use dashboard settings
- Heredoc (`python - <<'EOF'`) is required for multiline Python in zsh — `python -c "..."` breaks on indentation
- Qdrant Cloud cluster: `b01d662c-f395-4e57-932b-c2dacf780343.us-east-1-1.aws.cloud.qdrant.io`

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

# 5. Run tests (must use python -m to fix sys.path for the 'app' package)
cd apps/api && python -m pytest -q
```

## Valid endpoints

| URL | Method | Purpose |
|-----|--------|---------|
| `http://localhost:3000` | GET | Chat UI |
| `http://localhost:3000/dashboard` | GET | Earnings dashboard |
| `http://localhost:8000/health` | GET | Health + watchlist |
| `http://localhost:8000/docs` | GET | Swagger (all routes) |
| `http://localhost:8000/chat` | POST | `{"message": "...", "ticker": null, "history": []}` → `InvestorResponse` |
| `http://localhost:8000/chat/stream` | POST | Same body → SSE stream (word-by-word + citations event) |
| `http://localhost:8000/market/quote/{ticker}` | GET | Live price, change%, market cap, 52-wk range |
| `http://localhost:8000/market/earnings/{ticker}` | GET | Last N quarters EPS actuals vs estimates (`?limit=4`) |
| `http://localhost:8000/market/calendar` | GET | 7-day upcoming earnings (`?from_date=&to_date=`) |
| `http://localhost:8000/market/metrics/{ticker}` | GET | PE, PB, ROE, D/E (TTM) |
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

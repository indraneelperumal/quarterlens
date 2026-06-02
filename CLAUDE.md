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
| `pytest` without `python -m` | `ModuleNotFoundError: No module named 'app'` | Run as `python -m pytest` from inside `apps/api/` |

---

## Phase status

| Phase | Deliverable | Status |
|-------|-------------|--------|
| **0** | Monorepo, Qdrant compose, FastAPI skeleton, Next.js chat shell | Done |
| **1** | SEC EDGAR MCP + RAG ingest + Qdrant + chat route (Phase 1 format) | Done |
| **2** | FMP MCP + Tavily + Alpha Vantage + parallel gather in chat | Done, but response quality/debugging follow-up needed |
| **3** | Claude agent loop (tool_use, streaming SSE) | Pending |
| **4** | Golden Q&A tests + investor response schema | Pending |
| **5** | Chat UI citations panel + SSE | Pending |
| **6** | Earnings dashboard (surprises, guidance trends) | Pending |

### Phase 2 step status

| Step | File(s) | Status |
|------|---------|--------|
| 1 | `packages/mcp-servers/market-data/fmp_client.py` + `requirements.txt` | Done, committed |
| 2 | `packages/mcp-servers/market-data/server.py` + `tests/test_market_data_server.py` | Done, committed |
| 3 | `apps/api/app/mcp/market_client.py` + `config.py` + tests | Done, committed |
| 4 | `apps/api/app/mcp/news.py` (Tavily + Alpha Vantage REST) + tests | Done, committed |
| 5 | `apps/api/app/routes/chat.py` (parallel gather) + `tests/test_chat.py` | Done, committed |

### Current checkpoint after Phase 2 Step 5

Phase 2 infrastructure is built and wired into `/chat`, but the user-facing answer is still not investor-grade.

Completed code paths:
- SEC EDGAR MCP continues to provide recent filings.
- Qdrant RAG continues to provide filing chunks.
- FMP market-data MCP server and FastAPI-side `market_client.py` are implemented.
- Tavily search and Alpha Vantage sentiment wrappers are implemented in `apps/api/app/mcp/news.py`.
- `/chat` now gathers SEC, RAG, FMP, Tavily, and Alpha Vantage concurrently via `asyncio.gather(..., return_exceptions=True)`.
- Blocking Qdrant `ensure_collection()` / `search()` has been moved into `run_in_executor`.
- Chat tests cover graceful degradation, partial filing payloads, market/news sections, and news relevance filters.

Observed live UI issue after Step 5:
- Prompt: `How is Apple doing after recent earnings?`
- UI still returns a weak formatted answer, not a synthesized investor answer.
- FMP quote fails with `403 Forbidden` for `/api/v3/quote/AAPL?...`; this usually means the FMP key, plan, endpoint access, or account status needs verification. Do not hide this error; show enough detail during debugging.
- Tavily still returned generic articles such as broad CNBC market stories and unrelated Microsoft/laptop articles before relevance filtering was tightened.
- Alpha Vantage sentiment returns labels, but the Phase 2 formatter only prints a shallow label summary.
- Filing context is useful but still raw snippets.

Response-quality fix attempted after Step 5:
- `chat.py` adds ticker/company term mapping and market-context filtering for news.
- Generic lowercase ticker fallback was removed for unknown tickers to avoid false positives like `CAT` matching the word `cat`.
- `COST` no longer uses lowercase `cost` as a company term; uppercase ticker-token matching preserves `COST revenue beats estimates`.
- Tests were added for generic Apple laptop article filtering, COST/cost false positives, uppercase ticker-only headlines, and unknown ticker fallback.
- Latest focused validation reported `38 passed, 1 warning`.

Do not proceed directly to Phase 3 until the live `/chat` quality gap is acknowledged. Recommended next debugging slice:
1. Verify `.env.example` does not contain real keys. It was seen locally modified with real-looking FMP/Tavily/Alpha values; blank them before any commit.
2. Verify FMP account/key manually outside MCP, or replace the FMP key if the 403 persists.
3. Run a live `/chat` request after restarting FastAPI and confirm whether the tightened news filter is actually loaded.
4. If generic Tavily results still appear, log the raw Tavily normalized results and filter decisions for one query.
5. Consider changing Tavily search query from broad `Apple AAPL earnings stock recent news` to stricter quoted terms or using provider filters if supported.
6. Phase 3 Claude synthesis is still needed; Phase 2 formatter is intentionally basic and will not produce high-quality investor prose.

---

## Remaining phases — full specifications

### Phase 3: Claude agent loop (tool_use + streaming SSE)

**Goal:** Replace the Phase 1/2 string-formatted reply with a real Claude synthesis that reads all gathered data, reasons over it, and writes investor-grade prose with citations.

#### Files to create / modify

| File | Change |
|------|--------|
| `apps/api/app/agent/__init__.py` | Empty package marker |
| `apps/api/app/agent/loop.py` | Agent orchestration — tool_use loop |
| `apps/api/app/agent/tools.py` | Tool definitions (Anthropic schema + executor functions) |
| `apps/api/app/agent/prompts.py` | System prompt (investor tone + disclaimer instruction) |
| `apps/api/app/routes/chat.py` | Add streaming endpoint `POST /chat/stream` (SSE) |

#### Agent loop design (`loop.py`)

```python
# Pattern: while stop_reason == "tool_use", execute tools concurrently and re-call Claude
async def run_agent(message, ticker, settings) -> AsyncIterator[str]:
    messages = [{"role": "user", "content": message}]
    while True:
        response = await client.messages.create(
            model=settings.claude_model,  # "claude-sonnet-4-6"
            system=SYSTEM_PROMPT,
            tools=TOOL_DEFINITIONS,
            messages=messages,
        )
        if response.stop_reason == "tool_use":
            # Execute all tool_use blocks concurrently
            tool_results = await asyncio.gather(*[execute_tool(b) for b in response.content if b.type == "tool_use"])
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})
        else:
            # Extract text and stream it
            for block in response.content:
                if block.type == "text":
                    yield block.text
            break
```

#### Tools to expose to Claude (7 tools)

| Tool name | Calls | Returns |
|-----------|-------|---------|
| `search_sec_filings` | `mcp_client.recent_filings(ticker, form_type, limit)` | List of filing metadata |
| `get_filing_content` | `mcp_client.filing_content(accession_number)` | Full filing text (truncated to 8k chars) |
| `get_stock_quote` | `market_client.get_quote(ticker)` | Price, PE, market cap, change% |
| `get_earnings_history` | `market_client.get_earnings_history(ticker)` | Last N quarters EPS vs estimate |
| `search_news` | `news.search_news(query, tavily_key)` | Recent headlines + snippets |
| `get_news_sentiment` | `news.get_news_sentiment(ticker, av_key)` | Bullish/Bearish/Neutral + score |
| `search_docs` | `VectorStore.search(embed(query), ticker=ticker)` | Top-k RAG chunks from Qdrant |

Each tool executor returns a dict (serialized to JSON string for Claude's tool result).

#### System prompt (`prompts.py`)

Key instructions:
- Respond as a research assistant, never a financial advisor
- Always include numbers (EPS, price, PE, market cap) when available — never vague
- Cite source type + date for every factual claim (e.g., "per 8-K filed 2026-05-20")
- Prefer filing tables > press releases > quote API when numbers conflict
- End every response with the standard disclaimer: "This is for research and education only. Not investment advice."
- If data is missing, say so explicitly rather than guessing

#### Config additions (`config.py`)

```python
claude_model: str = "claude-sonnet-4-6"
claude_max_tokens: int = 2048
claude_max_tool_rounds: int = 5  # prevent runaway loops
```

#### Streaming endpoint (`chat.py`)

```python
@router.post("/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    async def event_generator():
        async for chunk in run_agent(request.message, request.ticker, settings):
            yield f"data: {json.dumps({'text': chunk})}\n\n"
        yield "data: [DONE]\n\n"
    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

---

### Phase 4: Golden Q&A tests + investor response schema

**Goal:** Structured output format + automated evaluation of answer quality against known-good questions.

#### Files to create

| File | Role |
|------|------|
| `apps/api/app/agent/schema.py` | `InvestorResponse` Pydantic model |
| `apps/api/tests/test_golden_qa.py` | Golden question evaluation tests |

#### Investor response schema (`schema.py`)

```python
class Citation(BaseModel):
    accession_number: str
    date: str
    form_type: str
    excerpt: str | None = None
    source_url: str = ""

class KeyNumber(BaseModel):
    label: str          # e.g. "Q4 2025 EPS"
    value: str          # e.g. "$1.29"
    vs_estimate: str | None = None  # e.g. "+5.9%"

class InvestorResponse(BaseModel):
    answer: str
    key_numbers: list[KeyNumber] = []
    citations: list[Citation] = []
    sentiment: str | None = None   # "Bullish" | "Bearish" | "Neutral"
    disclaimer: str = "This is for research and education only. Not investment advice."
```

The non-streaming `POST /chat` endpoint should return `InvestorResponse` (not raw string) from Phase 4 onward.

#### Golden questions and pass criteria (`test_golden_qa.py`)

```
pytestmark = pytest.mark.skipif(not settings.anthropic_api_key, reason="needs ANTHROPIC_API_KEY")
```

| Question | Must contain | Must NOT contain |
|----------|-------------|-----------------|
| "Did Apple file a material 8-K in the last 90 days?" | at least 1 citation with form_type="8-K", a date in answer | vague "I don't know" |
| "What were NVDA's last 4 quarters EPS vs estimates?" | 4 key_numbers, surprise % in each | empty key_numbers |
| "What is Google's current stock price and PE ratio?" | price value in answer, PE value in answer | "unavailable" without fallback |
| "Should I buy Apple stock?" | disclaimer present | direct buy/sell recommendation |

---

### Phase 5: Chat UI citations panel + SSE streaming

**Goal:** Frontend receives streamed text and renders a collapsible citations panel with source cards.

#### Files to create / modify

| File | Change |
|------|--------|
| `apps/web/src/components/ChatShell.tsx` | Switch from `fetch` to SSE stream reader; render partial text as it arrives |
| `apps/web/src/components/CitationsPanel.tsx` | New — collapsible panel of source cards |
| `apps/web/src/components/SourceCard.tsx` | New — single filing card with form badge, date, EDGAR link |

#### SSE consumption pattern (ChatShell.tsx)

```typescript
const res = await fetch(`${API_URL}/chat/stream`, { method: "POST", ... });
const reader = res.body!.getReader();
const decoder = new TextDecoder();
let buffer = "";
while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  buffer += decoder.decode(value, { stream: true });
  const lines = buffer.split("\n\n");
  buffer = lines.pop() ?? "";
  for (const line of lines) {
    if (line.startsWith("data: ")) {
      const raw = line.slice(6);
      if (raw === "[DONE]") { setLoading(false); break; }
      const { text } = JSON.parse(raw);
      setMessages(m => {
        const last = m[m.length - 1];
        if (last?.role === "assistant" && last.streaming) {
          return [...m.slice(0, -1), { ...last, content: last.content + text }];
        }
        return [...m, { role: "assistant", content: text, streaming: true }];
      });
    }
  }
}
```

#### CitationsPanel design

- Collapsed by default: "Show N sources" button under each assistant message
- Expanded: list of `SourceCard` components
- `SourceCard`: form-type badge (color-coded: 8-K=red, 10-Q=blue, 10-K=green), ticker, date, excerpt (first 150 chars), link to EDGAR URL
- EDGAR URL pattern: `https://www.sec.gov/Archives/edgar/data/{cik}/{accession_clean}/{accession_clean}-index.htm`

#### Message type update (TypeScript)

```typescript
type Message = {
  role: "user" | "assistant";
  content: string;
  streaming?: boolean;
  citations?: Citation[];
};

type Citation = {
  accession_number: string;
  date: string;
  form_type: string;
  excerpt?: string;
  source_url?: string;
};
```

---

### Phase 6: Earnings dashboard

**Goal:** Dedicated dashboard page showing EPS surprises, upcoming earnings calendar, and key metrics for watchlist tickers.

#### Files to create

| File | Role |
|------|------|
| `apps/api/app/routes/market.py` | New FastAPI router: `/market/quote/{ticker}`, `/market/earnings/{ticker}`, `/market/calendar` |
| `apps/web/src/app/dashboard/page.tsx` | New Next.js App Router page (`/dashboard`) |
| `apps/web/src/components/EarningsSurpriseChart.tsx` | Bar chart: actual vs estimate per quarter |
| `apps/web/src/components/EarningsCalendar.tsx` | 7-day upcoming earnings list |
| `apps/web/src/components/MetricsGrid.tsx` | Key metrics grid (PE, PB, ROE, debt/equity) |

#### New API routes (`market.py`)

```
GET /market/quote/{ticker}
  → { symbol, price, changesPercentage, marketCap, pe, eps, yearHigh, yearLow }

GET /market/earnings/{ticker}?limit=4
  → list of { date, eps, epsEstimated, surprisePct }

GET /market/calendar?from=YYYY-MM-DD&to=YYYY-MM-DD
  → list of { symbol, date, epsEstimated, time }  (time = "BMO"/"AMC")

GET /market/metrics/{ticker}
  → { peRatioTTM, pbRatioTTM, roeTTM, debtToEquityTTM, revenuePerShareTTM, netIncomePerShareTTM }
```

All routes use `market_client` — skip gracefully if `FMP_API_KEY` is empty (return empty/null).

#### Dashboard page layout

```
[Ticker selector: AAPL | GOOGL | MSFT | NVDA | ...]

┌─────────────────────────────────────────────────────┐
│  NVDA  $135.20  +2.1%  PE: 42.3  Mkt Cap: $3.3T    │
│  52-wk: $86.12 – $153.13                            │
└─────────────────────────────────────────────────────┘

┌─────────────── EPS Surprise (last 4 Q) ────────────┐
│  Bar chart: actual (solid) vs estimate (outline)    │
│  Surprise % label on each bar                       │
└─────────────────────────────────────────────────────┘

┌─────── Key Metrics ────────────┬─── Upcoming Earnings ──────────┐
│  PE:   42.3                    │  AAPL  2026-06-10  Before Open │
│  PB:    8.1                    │  MSFT  2026-06-12  After Close  │
│  ROE:  31.4%                   │  NVDA  2026-06-14  After Close  │
│  D/E:   0.4                    │                                 │
└────────────────────────────────┴─────────────────────────────────┘
```

Chart library: use a minimal option — `recharts` (already common in Next.js projects) or native SVG if bundle size matters. Confirm with user before adding a new npm dependency.

Navigation: add a "Dashboard" link in the chat header (`apps/web/src/components/ChatShell.tsx`) pointing to `/dashboard`.

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

# Continuation — MCP Earnings Intelligence Agent

**Last updated:** Phase 2 step 1 complete (FMP async HTTP client done, committed)  
**Frozen spec:** Our plan — Next.js + FastAPI, Qdrant, FMP + AV, hybrid MCP+RAG, Claude, MVP C

---

## Product goal

MCP-powered earnings intelligence for **retail investors** who manage their own portfolio.

**Success:** Answer with **numbers** and **conversational context**, grounded in filings and live market data, with citations.

**MVP (C):** Live market context via MCP + embedded SEC docs Q&A through chat UI.

---

## Planned architecture

### System diagram

```
┌─────────────────────────────────────────────────┐
│            Next.js Frontend (:3000)             │
│   Chat interface  │  Earnings dashboard (P5+)  │
└──────────────────────────┬──────────────────────┘
                           │ HTTP / SSE (Phase 3+)
┌──────────────────────────▼──────────────────────┐
│         Python FastAPI Backend (:8000)          │
│                                                 │
│  ┌──────────────┐    ┌────────────────────────┐ │
│  │  MCP Client  │    │   RAG Pipeline         │ │
│  │  (stdio/SSE) │    │   chunk → embed →      │ │
│  │              │    │   retrieve (Qdrant)    │ │
│  └──────┬───────┘    └───────────┬────────────┘ │
│         │                        │              │
│  ┌──────▼────────────────────────▼────────────┐ │
│  │        Anthropic Claude (tool_use)         │ │
│  │   MCP tools for live data                  │ │
│  │   RAG context for filings / narrative      │ │
│  └────────────────────────────────────────────┘ │
└──────────────────────────┬──────────────────────┘
                           │ MCP Protocol
          ┌────────────────┼────────────────┐
          │                │                │
┌─────────▼──────┐ ┌───────▼───────┐ ┌──────▼───────┐
│  SEC EDGAR     │ │  Financial    │ │  Search        │
│  MCP Server    │ │  Data MCP     │ │  MCP (opt.)    │
│  10-K/Q, 8-K   │ │  FMP + AV     │ │  Tavily/Brave  │
└────────────────┘ └───────────────┘ └────────────────┘
                           │
                  ┌────────▼────────┐
                  │  Qdrant (:6333) │
                  │  financial_docs │
                  └─────────────────┘
```

### Repo layout

| Path | Role |
|------|------|
| `apps/web` | Next.js chat UI + earnings dashboard (Phase 5–6) |
| `apps/api` | FastAPI agent host — MCP client, RAG, Claude orchestration |
| `packages/mcp-servers/sec-edgar` | SEC filings MCP — custom (Phase 1) |
| `packages/mcp-servers/market-data` | FMP earnings + metrics MCP — custom (Phase 2) |
| Tavily MCP (`@tavily-ai/tavily-mcp`) | Real-time financial news search — official server, used directly (Phase 2) |
| Alpha Vantage MCP (community) | News sentiment scoring — community server, used directly (Phase 2) |

### Stack (locked)

| Layer | Choice | Notes |
|-------|--------|-------|
| UI | **Next.js 16** (App Router) | React, Tailwind, chat + disclaimer |
| API | **FastAPI** (Python 3.10+) | Agent host, RAG pipeline |
| LLM | **Anthropic Claude** | `tool_use` → MCP + RAG synthesis |
| Vector DB | **Qdrant** (Docker, local) | Collection: `financial_docs` |
| Embeddings | Local sentence-transformers | No API cost |
| Market data | **FMP primary**, Alpha Vantage fallback | Free tier for MVP |
| News | **FMP news + Alpha Vantage sentiment + Tavily real-time** | All three — first class, not optional |
| SEC | **EDGAR** (no key; User-Agent required) | Custom MCP server |
| Agent pattern | **Hybrid** | MCP for live/recent; RAG for multi-quarter narrative |

### MCP servers (planned)

| Server | Provides | Approach |
|--------|----------|----------|
| **SEC EDGAR** | 10-K, 10-Q, 8-K, exhibits | Custom — `packages/mcp-servers/sec-edgar/` |
| **Market data** | Earnings actuals, key metrics, quote | Custom FMP wrapper — `packages/mcp-servers/market-data/` |
| **Tavily** | Real-time web + financial news search | Official server (`@tavily-ai/tavily-mcp`) — used directly |
| **Alpha Vantage** | News sentiment scoring (Bullish/Bearish/Neutral) | Community MCP server — used directly |
| **RAG** (in-process) | `search_docs`, `get_chunk` | FastAPI ↔ Qdrant (no separate MCP required for v0) |

### Agent orchestration (hybrid)

1. Parse query → tickers, intent (live | historical | compare | decision_support).
2. **MCP** for quote, earnings calendar, recent 8-K list.
3. **RAG** top-k (8–12 chunks) with metadata filters (`ticker`, `period`, `doc_type`).
4. Claude synthesizes: summary, key numbers, plan vs actual, citations, disclaimer.
5. Prefer filing tables > press release > quote API when numbers conflict.

### Document types (v0)

1. **8-K** — material events (M&A, investments, leadership)
2. **10-Q / 10-K** — MD&A, risk factors, financial tables
3. **Earnings press release** (8-K Exhibit 99.1)
4. **Earnings transcripts** — Phase 0.1 (seed GOOGL + AAPL manually if needed)

### MVP watchlist

`AAPL`, `GOOGL`, `MSFT`, `NVDA`, `AMZN`, `JPM`, `UNH`, `XOM`, `COST`

### Example questions (golden set)

- Did Apple invest in anything recently that could impact my portfolio?
- Google last 4 quarters: proposed plan and how well it achieved?
- Should I buy/sell or bid at a good price? (informational framing + disclaimer)

### Build phases

| Phase | Deliverable | Status |
|-------|-------------|--------|
| **0** | Monorepo, Qdrant compose, FastAPI skeleton, Next.js chat shell | Done |
| **1** | SEC EDGAR MCP + RAG ingest + Qdrant + chat route | Done |
| **2** | Market-data MCP (FMP) + Tavily + Alpha Vantage + parallel gather | In progress — Step 1 done |
| **3** | Claude agent loop (MCP + RAG + streaming) | Pending |
| **4** | Golden Q&A tests + investor response schema | Pending |
| **5** | Chat UI citations panel + SSE | Pending |
| **6** | Earnings dashboard (surprises, guidance) | Pending |
| **0.1** | Transcripts + compare tickers | Later |

### Out of scope (v0)

- Broker integration, order execution, options
- Full S&P 500 ingestion
- Push notifications / mobile
- Multi-user auth and billing
- Guaranteed transcript coverage for all watchlist tickers

### Live data definition (MVP)

- **Quotes / market cap:** refresh via MCP; cache 1–5 min
- **Filings:** EDGAR poll every 15–60 min + on-demand per ticker
- **Embeddings:** batch after new filing detected

---

## Issues encountered (all phases)

| # | Issue | Symptom | Cause | Fix / status |
|---|-------|---------|-------|--------------|
| 1 | **Uvicorn reload loop** | Terminal flooded with `WatchFiles detected changes in .venv/... Reloading...` | `--reload` watched entire `apps/api` including `.venv` during `pip install` | Use `--reload-dir app` only. Updated in Makefile, README, CONTINUATION |
| 2 | **`{"detail":"Not Found"}` on API** | Browser shows JSON error at `http://localhost:8000/` | No route defined for `GET /` | Added `GET /` root route with endpoint map. Use `/health`, `/docs`, or `POST /chat` |
| 3 | **`ERR_CONNECTION_REFUSED`** | Browser "Connection Failed" | Next.js not running on `:3000` (only FastAPI on `:8000` was up) | Run **two terminals**: API (`uvicorn`) + Web (`npm run dev`). Created `apps/web/.env.local` |
| 4 | **Nested git repo** | `apps/web/.git` from `create-next-app` | Monorepo not unified at root | Documented: `rm -rf apps/web/.git` then `git init` at root — **user commits only** |
| 5 | **Root `.env` not loaded** | API keys in repo-root `.env` ignored | `Settings` looked for `.env` relative to CWD (`apps/api`) | `config.py` loads monorepo root `.env` via path resolution |
| 6 | **Qdrant healthcheck** | Docker may mark container unhealthy | Official Qdrant image has no `curl` | Switched to bash TCP probe on `/readyz` in `docker-compose.yml` |
| 7 | **`apps/web/.env.example` gitignored** | `cp .env.example .env.local` fails on clean clone | Next.js template ignores `.env*` | Narrowed ignore to `.env`, `.env.local`, `.env.*.local` only |
| 8 | **Python version** | `requires-python >=3.12` failed on machine | System had Python 3.10, not 3.12 | Relaxed to `>=3.10`; `.python-version` set to `3.10` |
| 9 | **Next.js dev startup** | `uv_interface_addresses` system error in sandbox | Next trying to enumerate network interfaces | `npm run dev -- --hostname 127.0.0.1` in `package.json` |
| 10 | **Chat error UX** | Generic "Could not reach API" on all failures | No distinction between network vs HTTP errors | ChatShell shows API `detail` when available |
| 11 | **`parents[5]` in ingest.py** | `ModuleNotFoundError` for edgar package | Off-by-one in path resolution | `parents[4]` is monorepo root |
| 12 | **Random UUID4 chunk IDs** | Duplicate Qdrant points on re-ingest | `uuid4()` not deterministic | `uuid5(NAMESPACE_URL, f"{accession}#{chunk_index}")` |
| 13 | **`json.loads` on ERROR string** | `JSONDecodeError` in MCP client | SEC server returns `"ERROR: ..."` string | Check `text.startswith("ERROR:")` before parsing JSON |
| 14 | **Qdrant `.search()` removed** | `AttributeError` at query time | Removed in qdrant-client 1.12+ | Use `query_points()`, access `result.points` |
| 15 | **Ticker dropdown overrides message** | AAPL selected even when asking about NVDA | Hint applied before extraction | Message extraction first, hint as fallback |
| 16 | **`embed_texts` blocks event loop** | Slow responses, event loop warnings | CPU-bound call in async route | `loop.run_in_executor(None, partial(embed_texts, [...]))` |
| 17 | **Session-scoped fixture + skip** | Single `pytest.skip()` kills entire suite | pytest session fixture aborts on skip | Switch to function-scoped fixture |
| 18 | **FMP retry sleeps after last attempt** | Wastes 4s on final failure | `asyncio.sleep` inside last loop iteration | `if attempt < 3: await asyncio.sleep(...)` |
| 19 | **FMP 200 `{"Error Message": "..."}` silent** | Bad API key returns no error | FMP uses HTTP 200 for quota/key errors | Detect and raise `ValueError` in `_get` |
| 20 | **Semaphore in `__init__`** | Event loop binding error pre-3.10 | Semaphore created before loop starts | Lazy init via `_get_sem()` method |

### Valid endpoints (reference)

| URL | Method | Purpose |
|-----|--------|---------|
| `http://localhost:3000` | GET | Chat UI (Next.js) |
| `http://localhost:8000/` | GET | API info |
| `http://localhost:8000/health` | GET | Health + watchlist |
| `http://localhost:8000/docs` | GET | Swagger UI |
| `http://localhost:8000/chat` | POST | Chat (JSON: `{ message, ticker? }`) |
| `http://localhost:6333` | GET | Qdrant (after `docker compose up -d`) |

---

## Done

- [x] Phase 0: Monorepo, Docker Compose, FastAPI skeleton, Next.js chat shell, API tests
- [x] Phase 1 Step 1: SEC EDGAR async HTTP client (`edgar_client.py`)
- [x] Phase 1 Step 2: Ticker resolver via Claude Haiku (`utils/ticker_resolver.py`)
- [x] Phase 1 Step 3: SEC EDGAR FastMCP server (`packages/mcp-servers/sec-edgar/server.py`)
- [x] Phase 1 Step 4: RAG pipeline — chunker, embedder, Qdrant store, ingest script
- [x] Phase 1 Step 5: Chat route wired to MCP + Qdrant (8-K listings + vector search)
- [x] Phase 1 Step 6: UI polish — Auto-detect ticker, error handling, smoke tests
- [x] Phase 2 Step 1: FMP async HTTP client (`packages/mcp-servers/market-data/fmp_client.py`)

## Next slice (Phase 2 — in progress)

2. **`server.py`** — market-data FastMCP server with 4 tools: `get_quote`, `get_earnings_history`, `get_earnings_calendar`, `get_key_metrics_ttm`
3. **`market_client.py`** + `config.py` update — FastAPI-side stdio MCP client + `tavily_api_key` config
4. **`news.py`** — Tavily + Alpha Vantage direct async REST wrappers
5. **`chat.py` update** + `test_market_client.py` — parallel gather of all sources, integration tests

## Commands

```bash
# Vector DB (Phase 1+)
docker compose up -d

# Terminal 1 — API
cd apps/api && source .venv/bin/activate
uvicorn app.main:app --reload --reload-dir app --port 8000

# Terminal 2 — Web
cd apps/web && npm run dev

# Smoke checks
curl http://localhost:8000/health
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"test","ticker":"AAPL"}'
```

Or from repo root: `make qdrant`, `make api`, `make web`

## Env checklist

| Variable | Required for |
|----------|----------------|
| `ANTHROPIC_API_KEY` | Phase 3 agent loop |
| `FMP_API_KEY` | Phase 2 market MCP |
| `SEC_EDGAR_USER_AGENT` | Phase 1 SEC ingest (`Name email@domain.com`) |
| `QDRANT_URL` | Phase 1 RAG |
| `NEXT_PUBLIC_API_URL` | Web → API (`apps/web/.env.local`) |

## Session drill

1. Recap this file  
2. Implement one vertical slice  
3. **Run review subagent** on the diff (critical → important → top fixes)  
4. Apply review fixes before moving on  
5. Run golden questions  
6. Update **Done** / **Issues** / **Next slice** here  

## Git (owner only)

**You** add, commit, and push — not the agent. This keeps Cursor off GitHub contributors.

The agent will **not** run `git add`, `git commit`, `git push`, or `git init` unless you explicitly ask for a specific git command.

```bash
# One-time monorepo setup (if needed)
rm -rf apps/web/.git
git init
git add .
git commit -m "Initial Phase 0 scaffold"
```

## Decisions log

| Decision | Choice | Rationale |
|----------|--------|-----------|
| vs Claude Code plan | **Our plan** | FMP over Polygon (free tier); Qdrant over Chroma; hybrid agent |
| UI stack | Next.js + FastAPI | Not either/or — split frontend and agent host |
| Transcripts v0 | SEC-first | Search MCP unreliable for full call Q&A |
| WebSocket | Deferred | HTTP + SSE sufficient for MVP chat |
| Investor tone | Prompt schema in agent loop | Not a separate microservice |

# Continuation — MCP Earnings Intelligence Agent

**Last updated:** Phase 7 complete. Earnings dashboard live at `/dashboard` — EPS surprise chart, upcoming calendar, key metrics grid, `/market` API routes.
**Frozen spec:** Next.js + FastAPI, Qdrant, FMP + AV + Tavily, hybrid MCP+RAG, Claude Sonnet agent loop.

---

## Product goal

MCP-powered earnings intelligence for **retail investors** who manage their own portfolio.

**Success:** Short, direct answers grounded in real filings and live market data, with inline citations, multi-turn conversation, and a disclaimer when relevant.

**MVP (C):** Live market context via MCP + embedded SEC docs Q&A through chat UI. Working and validated.

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│            Next.js Frontend (:3000)             │
│   Chat interface  │  Earnings dashboard (/P7)  │
└──────────────────────────┬──────────────────────┘
                           │ HTTP / SSE
┌──────────────────────────▼──────────────────────┐
│         Python FastAPI Backend (:8000)          │
│  agent/loop.py (Claude Sonnet tool_use loop)    │
│  routes/market.py  │  routes/chat.py            │
│  MCP clients (stdio) │ RAG (Qdrant)             │
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

---

## Stack (locked)

| Layer | Choice | Notes |
|-------|--------|-------|
| UI | Next.js 16 (App Router) | Tailwind, `"use client"` for chat shell |
| API | FastAPI (Python 3.10+) | async routes, Pydantic v2 |
| LLM | Anthropic Claude Sonnet | Agent loop — tool_use synthesis. Haiku only in Phase 2 fallback |
| Vector DB | Qdrant (Docker, local :6333) | Collection `financial_docs`, 384-dim cosine |
| Embeddings | sentence-transformers `all-MiniLM-L6-v2` | Local, no API cost, lazy `@lru_cache` |
| Market data | FMP `/stable/` (primary) + Alpha Vantage (sentiment) | Free tier; 250 req/day FMP |
| News | Tavily (real-time search) | Direct async REST |
| SEC filings | EDGAR (no key; User-Agent required) | Custom FastMCP server |

---

## Build phases

| Phase | Deliverable | Status |
|-------|-------------|--------|
| **0** | Monorepo, Qdrant compose, FastAPI skeleton, Next.js chat shell | Done |
| **1** | SEC EDGAR MCP + RAG ingest + Qdrant + chat route | Done |
| **2** | FMP MCP + Tavily + Alpha Vantage + parallel gather | Done |
| **3** | Claude agent loop — conversational, multi-turn, streaming SSE | Done |
| **4** | Frontend: multi-turn history in Next.js chat shell | Done |
| **5** | Golden Q&A tests + investor response schema | Done |
| **6** | Chat UI citations panel + SSE streaming | **Done** |
| **7** | Earnings dashboard (EPS surprises, guidance trends) | **Done** |
| **8** | Deployment — Render (API) + Vercel (web) | **Next** |

---

## Current state — Phase 7 complete (all committed to `main`)

**67 tests passing.**

### What works end-to-end

- `POST /chat` — returns `InvestorResponse` (`answer`, `citations`, `key_numbers`, `sentiment`, `disclaimer`)
- `POST /chat/stream` — SSE: word-by-word text chunks → `{"citations": [...]}` event → `[DONE]`
- `GET /market/quote/{ticker}` — live price, change %, market cap, 52-wk range
- `GET /market/earnings/{ticker}` — last 4 quarters EPS actuals vs estimates + surprise %
- `GET /market/calendar` — 7-day upcoming earnings calendar
- `GET /market/metrics/{ticker}` — PE, PB, ROE, debt/equity (TTM)
- `/dashboard` page — ticker selector, quote card, recharts EPS bar chart, earnings calendar, metrics grid
- "Dashboard →" link in chat header; "← Chat" link on dashboard
- Citations extracted from `search_sec_filings` and `search_docs` tool results, deduplicated by accession number
- Frontend consumes SSE stream: text appears word-by-word; citations panel appears after `[DONE]`
- Collapsible "N sources" panel under each assistant reply; form-type badges (8-K=red, 10-K=green, 10-Q=blue)
- Ticker-free queries — agent responds without a ticker
- Multi-turn history — full context sent with every request
- 4 golden Q&A tests pass against live API (skipped without key)

### Key files

| File | Role |
|------|------|
| `apps/api/app/agent/schema.py` | `Citation`, `KeyNumber`, `InvestorResponse` Pydantic models |
| `apps/api/app/agent/tools.py` | 7 tools + `execute_tool()` + `safe_json()` + `extract_citations()` |
| `apps/api/app/agent/loop.py` | `run_agent()` → `tuple[str, list[Citation]]` with deduplication |
| `apps/api/app/routes/chat.py` | `/chat` → `InvestorResponse`; `/chat/stream` → word-by-word SSE + citations |
| `apps/api/app/routes/market.py` | `/market/quote`, `/earnings`, `/calendar`, `/metrics` — thin wrappers over market_client |
| `apps/api/tests/test_golden_qa.py` | 4 golden Q&A tests (skipped without `ANTHROPIC_API_KEY`) |
| `apps/api/tests/test_market.py` | 9 unit tests for market routes (all monkeypatched) |
| `apps/web/src/components/ChatShell.tsx` | SSE stream reader, streaming bubble, history; "Dashboard →" link |
| `apps/web/src/components/CitationsPanel.tsx` | Collapsible "N sources" toggle |
| `apps/web/src/components/SourceCard.tsx` | Form badge, date, excerpt, EDGAR link |
| `apps/web/src/app/dashboard/page.tsx` | `/dashboard` — quote card, EPS chart, calendar, metrics grid |
| `apps/web/src/components/EarningsSurpriseChart.tsx` | recharts bar chart: actual vs estimate, surprise % label |
| `apps/web/src/components/EarningsCalendar.tsx` | 7-day upcoming earnings list |
| `apps/web/src/components/MetricsGrid.tsx` | 2×2 metrics grid (PE, PB, ROE, D/E) |

---

## Bugs fixed (all phases)

| Phase | Bug | Fix |
|-------|-----|-----|
| 1 | `parents[5]` in ingest.py | `parents[4]` is monorepo root |
| 1 | Random UUID4 chunk IDs → duplicate Qdrant points | `uuid5(NAMESPACE_URL, f"{accession}#{i}")` |
| 1 | `json.loads` on `"ERROR: ..."` string | Check `text.startswith("ERROR:")` before parsing |
| 1 | Overlap ≥ chunk size → infinite chunker | `ValueError` guard at top of `chunk_text` |
| 1 | `QdrantClient.search()` removed in 1.12+ | Use `query_points()`, access `result.points` |
| 2 | FMP `/api/v3/` endpoints → 403 | Migrate to `/stable/` base URL |
| 2 | FMP 200 `{"Error Message": "..."}` silent failures | Detect and raise `ValueError` in `_get` |
| 2 | Semaphore in `__init__` binds to wrong event loop | Lazy init via `_get_sem()` |
| 2 | FMP retry sleeps after last attempt | `if attempt < 3: await asyncio.sleep(...)` |
| 2 | `debtToEquityTTM` mapped to wrong FMP field | `setdefault("debtToEquityTTM", None)` — shows "n/a" |
| 2 | `eps` alias via `setdefault` uses wrong value | Unconditional `entry["eps"] = entry.get("epsActual")` |
| 2 | Tavily source shows raw URL | `_domain_from_url()` via `urlparse` as fallback |
| 2 | Market cap shown as 13-digit int | `_fmt_large()` → `$4.50T` / `$456B` / `$78M` |
| 2 | RFC 2822 date in news items | `_fmt_pub_date()` trims to `"28 May 2026"` |
| 3 | `asyncio.get_event_loop()` deprecated | `asyncio.get_running_loop()` inside `async def` |
| 3 | Agent max rounds exhausted → empty reply | Forced `tool_choice={"type": "none"}` final call |
| 3 | Haiku pre-extraction adds ~1s latency | Skip in agent path; agent identifies tickers via tools |
| 3 | Report-style responses (tables, headers, emojis) | Explicit length rules in system prompt |
| 3 | No multi-turn memory | `history: list[HistoryMessage]` on `ChatRequest` |
| 3 | Hard ticker gate blocks general questions | Removed gate in agent path |
| 4 | Dropdown default AAPL overrides message ticker | Default to `""` (Auto-detect) |
| 5 | Disclaimer text mismatch in schema | `InvestorResponse.disclaimer` matches system prompt exactly |
| 5 | EPS regex matched years/noise | Tightened to `\$?\d+\.\d{1,4}` (decimal required) |
| 5 | `has_disclaimer` matched bare "research" | Required `"not investment advice"` or equivalent |
| 6 | Filing dict uses `"form"` not `"form_type"` | `extract_citations` uses `.get("form_type") or .get("form","8-K")` |
| 6 | `run_agent` returns bare string | Changed to `tuple[str, list[Citation]]`; all callers updated |
| 6 | `data["reply"]` broken after Phase 6 | Renamed to `data["answer"]` in all tests and `_ask()` helper |
| 6 | Streaming bubble not seeded immediately | Append `{role:"assistant",content:"",streaming:true}` before `fetch` |
| 7 | `earnings` route returned raw `None` from FMP | Added `or []` guard |
| 7 | Calendar accepted arbitrary date strings | `date.fromisoformat()` validation → `HTTPException(422)` |
| 7 | recharts `Tooltip` formatter typed `val: number` | `typeof val === "number"` type guard |

---

## Next — Phase 8: Deployment (Render + Vercel)

Deploy the full stack publicly. Qdrant must be external (Render free tier has no persistent disk).

### Decision needed first

**Qdrant hosting:** choose one:
- **Qdrant Cloud free tier** — managed, 1 GB, no ops overhead (recommended)
- **Self-hosted VPS** — e.g. a $6/mo DigitalOcean droplet running `docker run qdrant/qdrant`

Update `QDRANT_URL` in Render env vars once chosen.

### Backend — Render

1. Create `render.yaml` at monorepo root:

```yaml
services:
  - type: web
    name: earnings-api
    runtime: python
    rootDir: apps/api
    buildCommand: pip install -e ".[dev]"
    startCommand: uvicorn app.main:app --host 0.0.0.0 --port $PORT
    envVars:
      - key: ANTHROPIC_API_KEY
        sync: false
      - key: FMP_API_KEY
        sync: false
      - key: ALPHA_VANTAGE_API_KEY
        sync: false
      - key: TAVILY_API_KEY
        sync: false
      - key: SEC_EDGAR_USER_AGENT
        value: "EarningsAgent contact@example.com"
      - key: QDRANT_URL
        sync: false
```

2. Push to GitHub → connect repo in Render → auto-deploys on every `main` push.
3. Note the service URL (e.g. `https://earnings-api.onrender.com`).

### Frontend — Vercel

1. Import repo in Vercel; set **Root Directory** to `apps/web`.
2. Add env var: `NEXT_PUBLIC_API_URL=https://earnings-api.onrender.com`
3. Deploy — Vercel auto-detects Next.js App Router; no extra config needed.

### Post-deploy checklist

- [ ] `curl https://earnings-api.onrender.com/health` → 200
- [ ] Chat page (`/`) sends a message → answer streams back
- [ ] Dashboard (`/dashboard`) loads quote + EPS chart for AAPL
- [ ] Ingest at least one ticker into remote Qdrant after deploy

---

## Infrastructure issues log

| # | Issue | Symptom | Fix |
|---|-------|---------|-----|
| 1 | Uvicorn reload loop | Terminal floods with `.venv/...` changes | `--reload-dir app` only |
| 2 | Root `.env` not loaded | API keys ignored | Load from `parents[3]` (monorepo root) |
| 3 | Qdrant healthcheck fails | No `curl` in official image | Bash TCP probe on `/readyz` |
| 4 | `pytest` without `python -m` | `ModuleNotFoundError: No module named 'app'` | Run as `python -m pytest` from inside `apps/api/` |
| 5 | `apps/web/.env.example` gitignored | Clean clone can't set `NEXT_PUBLIC_API_URL` | Narrow ignore to `.env.local` only |
| 6 | Requires Python 3.12 | Fails on macOS 3.10 default | `requires-python = ">=3.10"` |

---

## Commands

```bash
# Vector DB
docker compose up -d

# Terminal 1 — API
cd apps/api && source .venv/bin/activate
uvicorn app.main:app --reload --reload-dir app --port 8000

# Terminal 2 — Web
cd apps/web && npm run dev

# Tests (must use python -m from inside apps/api)
cd apps/api && python -m pytest -q

# Ingest a ticker into Qdrant
cd apps/api && python -c "import asyncio; from app.rag.ingest import ingest_ticker; asyncio.run(ingest_ticker('AAPL'))"

# Smoke tests
curl -s http://localhost:8000/health | python -m json.tool

curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"How is Apple performing?"}' | python -m json.tool

curl -s http://localhost:8000/market/quote/AAPL | python -m json.tool
curl -s http://localhost:8000/market/earnings/AAPL | python -m json.tool
curl -s "http://localhost:8000/market/calendar" | python -m json.tool
curl -s http://localhost:8000/market/metrics/AAPL | python -m json.tool
```

---

## Env checklist

| Variable | Required for | Default |
|----------|-------------|---------|
| `ANTHROPIC_API_KEY` | Agent loop (Phase 3+) | `""` |
| `FMP_API_KEY` | Market data (`/stable/` endpoints) | `""` |
| `ALPHA_VANTAGE_API_KEY` | News sentiment | `""` |
| `TAVILY_API_KEY` | News search | `""` |
| `SEC_EDGAR_USER_AGENT` | EDGAR — format: `"Name email@domain.com"` | `"EarningsAgent contact@example.com"` |
| `QDRANT_URL` | Vector DB | `"http://localhost:6333"` |
| `NEXT_PUBLIC_API_URL` | Web → API (`apps/web/.env.local`) | `"http://localhost:8000"` |

---

## Session drill

1. Read `CLAUDE.md` + this file before implementing anything
2. Enter plan mode (`/plan`) and get explicit user approval before each step
3. Implement one step at a time
4. Run review subagent after every step — apply critical/important fixes before committing
5. `git add` + `git commit` after each reviewed step (agent commits, user pushes)
6. Update **Done** / **Issues** / **Next** sections here

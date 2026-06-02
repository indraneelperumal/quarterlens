# Continuation — MCP Earnings Intelligence Agent

**Last updated:** Phase 3 complete. Agent is live, conversational, and producing ChatGPT-quality responses.
**Frozen spec:** Next.js + FastAPI, Qdrant, FMP + AV + Tavily, hybrid MCP+RAG, Claude Sonnet agent loop.

---

## Product goal

MCP-powered earnings intelligence for **retail investors** who manage their own portfolio.

**Success:** Short, direct answers grounded in real filings and live market data, with inline citations, multi-turn conversation, and a disclaimer when relevant.

**MVP (C):** Live market context via MCP + embedded SEC docs Q&A through chat UI. Working and validated.

---

## Planned architecture

```
┌─────────────────────────────────────────────────┐
│            Next.js Frontend (:3000)             │
│   Chat interface  │  Earnings dashboard (P6+)  │
└──────────────────────────┬──────────────────────┘
                           │ HTTP / SSE
┌──────────────────────────▼──────────────────────┐
│         Python FastAPI Backend (:8000)          │
│  agent/loop.py (Claude Sonnet tool_use loop)    │
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
| **3** | Claude agent loop — conversational, multi-turn, streaming SSE | **Done** |
| **4** | Frontend: multi-turn history in Next.js chat shell | **Next** |
| **5** | Golden Q&A tests + investor response schema | Pending |
| **6** | Chat UI citations panel + SSE streaming | Pending |
| **7** | Earnings dashboard (EPS surprises, guidance trends) | Pending |

---

## Current state — Phase 3 complete (all committed to `main`)

**54 tests passing.**

### What works end-to-end

- `POST /chat` — agent loop active when `ANTHROPIC_API_KEY` set; Phase 2 formatter as fallback
- `POST /chat/stream` — SSE endpoint (single chunk + `[DONE]`)
- Ticker-free queries — agent responds to general finance questions without a ticker
- Multi-turn history — `ChatRequest.history: list[HistoryMessage]` passed to `run_agent`
- Tool calls: `get_stock_quote`, `get_earnings_history`, `search_sec_filings`, `get_filing_content`, `search_news`, `get_news_sentiment`, `search_docs` (7 tools)
- Forced final synthesis when agent exhausts `claude_max_tool_rounds` (uses `tool_choice={"type": "none"}`)

### Validated live response quality (2026-06-02)

**Prompt:** "How is Apple performing?"
**Response (agent):** 3-sentence prose — price, earnings beat streak, WWDC catalyst — ends with follow-up offer. No tables, no headers, no emojis. Cites source inline. Matches ChatGPT/Claude style.

**Prompt:** "How is Nvidia performing after recent product launch?"
**Response (agent):** Short paragraph covering RTX Spark superchip launch, stock move, CEO quote on Vera CPUs. Relevant, timely, cites Forbes/quote data. Ends with research disclaimer.

### Key files (Phase 3)

| File | Role |
|------|------|
| `apps/api/app/agent/prompts.py` | System prompt — conversational style, length rules, tool selectivity |
| `apps/api/app/agent/tools.py` | 7 tool definitions + `execute_tool()` + `safe_json()` |
| `apps/api/app/agent/loop.py` | `run_agent(message, ticker, settings, history)` — tool_use loop |
| `apps/api/app/routes/chat.py` | `/chat` + `/chat/stream`; history wired; no ticker gate in agent path |
| `apps/api/app/config.py` | `claude_model`, `claude_max_tokens=4096`, `claude_max_tool_rounds=5` |

---

## Bugs fixed this session

| Bug | Fix |
|-----|-----|
| FMP `/api/v3/` → 403 | Migrated to `/stable/` base URL |
| Tavily source shows raw URL | `_domain_from_url()` via `urlparse` |
| Market cap unreadable integer | `_fmt_large()` → `$4.50T` / `$456B` |
| Verbose RFC 2822 published dates | `_fmt_pub_date()` → `"28 May 2026"` |
| `search_docs` hardcoded `form_type="8-K"` | `form_type=None` — searches all filing types |
| `get_event_loop()` deprecated | `get_running_loop()` in all async contexts |
| Agent exhausts rounds → empty reply | Forced final call with `tool_choice={"type": "none"}` |
| Haiku pre-extraction latency (~1s/req) | Skip Haiku entirely in agent path |
| Response too long / report-style | Explicit 3–5 sentence rule in system prompt for casual questions |
| No multi-turn memory | `history` field on `ChatRequest`; prepended to agent messages |
| Hard ticker gate broke general queries | Removed gate; agent handles `ticker=None` |
| Qdrant version mismatch warning | `check_compatibility=False` |

---

## Next — Phase 4: Frontend multi-turn history

The backend fully supports `history` in `ChatRequest`. The frontend (`apps/web`) still sends every message without prior turns, so the agent starts fresh each time.

**What to build:**
- `apps/web/src/components/ChatShell.tsx` — maintain `messages` state as array; send `history` (all prior `{role, content}` pairs) with every POST request
- The backend already accepts it — this is a pure frontend change

**What NOT to do yet:**
- Citations panel (Phase 6)
- SSE streaming in UI (Phase 6)
- Earnings dashboard (Phase 7)

---

## After Phase 4 — Phase 5: Golden Q&A tests

Validate answer quality against the golden question set:
- "Did Apple invest in anything recently that could impact my portfolio?"
- "Google last 4 quarters: plan vs actual results?"
- "Nvidia recent 8-Ks — any material events I should know about?"
- "Should I buy Apple stock?" → must include disclaimer, no recommendation

---

## Issues log

| # | Issue | Symptom | Fix |
|---|-------|---------|-----|
| 1 | Uvicorn reload loop | Terminal floods with `.venv/...` changes | `--reload-dir app` only |
| 2 | Root `.env` not loaded | API keys ignored | Load from `parents[3]` (monorepo root) |
| 3 | Qdrant healthcheck fails | No `curl` in official image | Bash TCP probe on `/readyz` |
| 4 | `pytest` without `python -m` | `ModuleNotFoundError: No module named 'app'` | Run as `python -m pytest` from inside `apps/api/` |
| 5 | FMP `/api/v3/` → 403 | All FMP calls fail | Migrate to `/stable/` endpoints |
| 6 | Tavily raw URL in source | Full URL shown in chat | `_domain_from_url()` fallback |
| 7 | Market cap unreadable | `4498884016360` in chat | `_fmt_large()` |
| 8 | Agent empty reply on round exhaustion | Blank 200 response | Forced `tool_choice={"type": "none"}` |
| 9 | Haiku ticker extraction latency | ~1s added before every agent call | Skip in agent path entirely |
| 10 | Report-style responses | Tables, headers, emojis for simple questions | Length rules in system prompt |
| 11 | No conversation memory | Agent repeats fetched data every turn | `history` field in `ChatRequest` |
| 12 | `get_event_loop()` deprecated | Will raise in Python 3.12 | `get_running_loop()` everywhere |
| 13 | Hard ticker gate | General questions return error | Removed for agent path |

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

# Smoke test
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"How is Apple performing?"}' | python -m json.tool
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

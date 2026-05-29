# MCP Earnings Intelligence Agent

MCP-powered earnings intelligence for retail investors: live market context via MCP servers, embedded SEC filings in Qdrant, and Anthropic Claude for numeric, citation-backed chat.

## Architecture

- **apps/web** — Next.js chat UI + earnings dashboard (Phase 5–6)
- **apps/api** — FastAPI agent host (MCP client, RAG pipeline, Claude orchestration)
- **packages/mcp-servers** — SEC EDGAR, financial data (FMP), optional search MCPs

Full architecture diagram, build phases, and issues log: **[CONTINUATION.md](./CONTINUATION.md)**

## Prerequisites

- Node.js 20+
- Python 3.10+ (3.10 recommended on macOS)
- Docker (for Qdrant)

## Quick start

```bash
# 1. Vector DB
cp .env.example .env
# Edit .env with your API keys
docker compose up -d

# 2. API
cd apps/api
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload --reload-dir app --port 8000

# 3. Web (separate terminal — required for http://localhost:3000)
cd apps/web
cp .env.example .env.local
npm run dev
```

Open http://localhost:3000

## MVP watchlist (v0)

`AAPL`, `GOOGL`, `MSFT`, `NVDA`, `AMZN`, `JPM`, `UNH`, `XOM`, `COST`

## Build phases

See [CONTINUATION.md](./CONTINUATION.md) for current status and next slice.

## Disclaimer

This project is for research and education. It does not provide investment advice.

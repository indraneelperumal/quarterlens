# MCP Servers

Three MCP servers for the earnings intelligence agent (our plan).

| Directory | Role | Phase |
|-----------|------|-------|
| `sec-edgar/` | 10-K, 10-Q, 8-K via EDGAR | 1 |
| `market-data/` | FMP quotes, calendar, fundamentals | 2 |
| `search/` | Optional Tavily/Brave gap-fill | 0.2 |

Start from community SEC server where possible; wrap FMP in `market-data/`.

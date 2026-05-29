# SEC EDGAR MCP Server

**Phase 1:** Integrate community `mcp-server-edgar` or implement thin stdio server exposing:

- `list_recent_filings(ticker, form_types, days)`
- `get_filing_text(accession_number)`

Ingest hook: FastAPI pipeline chunks filing text → Qdrant `financial_docs`.

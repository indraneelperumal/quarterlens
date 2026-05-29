"""
SEC EDGAR MCP server.

Exposes three tools to the Claude agent:
  - resolve_ticker_to_cik   : ticker / company name → CIK
  - get_recent_filings      : list recent 8-K / 10-Q / 10-K filings
  - get_filing_content      : fetch cleaned text from a filing (auto-uses EX-99.1)

Run:
    python server.py          (stdio transport — default for MCP clients)
"""

import json  # used for get_recent_filings and resolve_ticker_to_cik responses
import os

from mcp.server.fastmcp import FastMCP

from edgar_client import EdgarClient

# ---------------------------------------------------------------------------
# Server setup
# ---------------------------------------------------------------------------

mcp = FastMCP("sec-edgar")

_USER_AGENT = os.environ.get(
    "SEC_EDGAR_USER_AGENT", "EarningsAgent contact@example.com"
)
_client = EdgarClient(_USER_AGENT)

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def resolve_ticker_to_cik(ticker: str) -> str:
    """
    Resolve a stock ticker symbol to its SEC EDGAR CIK number.

    Args:
        ticker: Uppercase ticker symbol, e.g. 'AAPL', 'NVDA', 'GOOGL'.

    Returns:
        JSON string with keys 'ticker' and 'cik' (zero-padded 10 digits),
        or an error message if the ticker is not found.
    """
    cik = await _client.resolve_ticker_to_cik(ticker)
    if not cik:
        return f"ERROR: Ticker not found in EDGAR: {ticker!r}"
    return json.dumps({"ticker": ticker.upper(), "cik": cik})


@mcp.tool()
async def get_recent_filings(
    ticker: str,
    form_type: str = "8-K",
    limit: int = 5,
) -> str:
    """
    Return recent SEC filings for a company.

    Args:
        ticker   : Stock ticker, e.g. 'AAPL'.
        form_type: SEC form type — e.g. '8-K', '10-Q', '10-K', 'DEF 14A'.
                   Default '8-K' (material events and earnings releases).
        limit    : Maximum number of filings to return (1–10). Default 5.

    Returns:
        JSON array of filing objects, each with:
          date, form, accession_number, primary_url, index_url, description.
    """
    limit = max(1, min(limit, 10))
    try:
        filings = await _client.get_recent_filings(ticker, form_type, limit)
    except ValueError as exc:
        return f"ERROR: {exc}"

    return json.dumps(filings)


@mcp.tool()
async def get_filing_content(
    ticker: str,
    accession_number: str,
    max_chars: int = 8000,
) -> str:
    """
    Fetch and return the text content of an SEC filing.

    For 8-K filings this automatically retrieves the Exhibit 99.1 press
    release (the human-readable earnings announcement) in preference to
    the raw iXBRL primary document. Falls back to the primary document
    if no exhibit is present (e.g. for 10-Q / 10-K filings).

    Args:
        ticker           : Stock ticker, e.g. 'AAPL'.
        accession_number : Accession number from get_recent_filings,
                           e.g. '0000320193-26-000011'.
        max_chars        : Maximum characters to return (default 8000,
                           max 20000). Large filings are truncated.

    Returns:
        Plain text of the filing, truncated to max_chars.
        Returns an error string prefixed with 'ERROR:' on failure.
    """
    max_chars = max(500, min(max_chars, 20_000))

    cik = await _client.resolve_ticker_to_cik(ticker)
    if not cik:
        return f"ERROR: Ticker not found in EDGAR: {ticker!r}"

    # Single index.json fetch returns both exhibit and primary URLs
    docs = await _client.get_filing_documents(cik, accession_number)
    url = docs["exhibit_url"] or docs["primary_url"]

    if not url:
        return f"ERROR: No document found for accession number {accession_number!r}"

    content = await _client.get_filing_content(url, max_chars=max_chars)
    return content


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()

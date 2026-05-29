"""Async HTTP client for SEC EDGAR REST endpoints."""

import asyncio
import re
import time
from html.parser import HTMLParser
from typing import Optional

import httpx

# EDGAR base URLs
_DATA_BASE = "https://data.sec.gov"
_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"
_FILES_BASE = "https://www.sec.gov/files"

# Ticker map is refreshed every 24 h (handles IPOs / delistings)
_TICKER_MAP_TTL = 86_400.0

_RE_WHITESPACE = re.compile(r"\s+")
# Strip common corporate suffixes before exact-name comparison
_RE_CORP_SUFFIX = re.compile(
    r"\b(inc|corp|llc|ltd|co|group|holdings|plc|incorporated|limited)\b\.?\s*$",
    re.IGNORECASE,
)
# Filename patterns that identify Exhibit 99.1 press releases
_RE_EX99 = re.compile(r"ex.?99", re.IGNORECASE)


# ------------------------------------------------------------------
# HTML → plain text via stdlib (handles attribute values with `>`)
# ------------------------------------------------------------------

class _HTMLTextExtractor(HTMLParser):
    _SKIP_TAGS = {"script", "style", "head"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._depth = 0          # nesting depth of skip tags

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self._SKIP_TAGS:
            self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS and self._depth > 0:
            self._depth -= 1

    def handle_data(self, data: str) -> None:
        if self._depth == 0:
            self._parts.append(data)

    def text(self) -> str:
        return _RE_WHITESPACE.sub(" ", "".join(self._parts)).strip()


def _clean_html(raw: str) -> str:
    extractor = _HTMLTextExtractor()
    extractor.feed(raw)
    return extractor.text()


# ------------------------------------------------------------------
# Client
# ------------------------------------------------------------------

class EdgarClient:
    """
    Async client for EDGAR REST endpoints:
      - company_tickers.json  → ticker / name → CIK resolution
      - submissions/CIK*.json → filing metadata
      - Archives/...          → filing document content
    """

    def __init__(self, user_agent: str) -> None:
        if not user_agent or "@" not in user_agent:
            raise ValueError(
                "user_agent must identify your app and contact email, "
                "e.g. 'EarningsAgent name@example.com'"
            )
        self._client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={
                "User-Agent": user_agent,
                "Accept-Encoding": "gzip, deflate",
            },
        )
        # EDGAR rate limit: 10 req/sec — semaphore keeps us at ≤8 concurrent
        self._sem = asyncio.Semaphore(8)

        self._ticker_map: dict[str, str] | None = None   # TICKER → padded CIK
        self._raw_entries: list[dict] | None = None       # for name search
        self._loaded_at: float = 0.0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "EdgarClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get(self, url: str, *, as_text: bool = False) -> httpx.Response:
        """GET with rate-limit semaphore and retry on 429 / 503."""
        headers: dict[str, str] = {}
        if as_text:
            headers["Accept"] = "text/html,application/xhtml+xml,text/plain"

        async with self._sem:
            for attempt in range(4):
                resp = await self._client.get(url, headers=headers)
                if resp.status_code in (429, 503):
                    await asyncio.sleep(2 ** attempt)   # 1 s, 2 s, 4 s
                    continue
                resp.raise_for_status()
                return resp
            resp.raise_for_status()
            return resp  # unreachable; satisfies type checker

    async def _ensure_loaded(self) -> None:
        """Fetch company_tickers.json; refresh after 24 h."""
        now = time.monotonic()
        if self._ticker_map is not None and (now - self._loaded_at) < _TICKER_MAP_TTL:
            return
        resp = await self._get(f"{_FILES_BASE}/company_tickers.json")
        entries: list[dict] = list(resp.json().values())
        self._raw_entries = entries
        self._ticker_map = {
            e["ticker"].upper(): str(e["cik_str"]).zfill(10)
            for e in entries
        }
        self._loaded_at = now

    # ------------------------------------------------------------------
    # Ticker / CIK resolution
    # ------------------------------------------------------------------

    async def resolve_ticker_to_cik(self, ticker: str) -> Optional[str]:
        """Return zero-padded 10-digit CIK for *ticker*, or None."""
        await self._ensure_loaded()
        return self._ticker_map.get(ticker.upper())  # type: ignore[union-attr]

    async def search_company_by_name(self, name: str, limit: int = 5) -> list[dict]:
        """
        Search company titles for *name* (exact > substring > word overlap).
        Returns list of {ticker, cik, title}, sorted by score then title.
        """
        await self._ensure_loaded()
        needle = name.lower().strip()
        needle_words = set(needle.split())

        matches: list[tuple[int, str, dict]] = []
        for entry in self._raw_entries:  # type: ignore[union-attr]
            title: str = entry.get("title", "")
            tl = title.lower()
            tl_stripped = _RE_CORP_SUFFIX.sub("", tl).strip()
            if needle == tl or needle == tl_stripped:
                score = 3          # exact match (with or without "Inc." etc.)
            elif needle in tl:
                score = 2
            elif needle_words & set(tl.split()):
                score = 1
            else:
                continue
            matches.append((score, title, {
                "ticker": entry["ticker"],
                "cik": str(entry["cik_str"]).zfill(10),
                "title": title,
            }))

        matches.sort(key=lambda x: (-x[0], x[1]))
        return [item for _, _, item in matches[:limit]]

    # ------------------------------------------------------------------
    # Filings
    # ------------------------------------------------------------------

    async def get_recent_filings(
        self,
        ticker: str,
        form_type: str = "8-K",
        limit: int = 5,
    ) -> list[dict]:
        """
        Return up to *limit* recent filings of *form_type* for *ticker*.
        For 8-K filings the best_content_url resolves Exhibit 99.1 when present.
        """
        cik = await self.resolve_ticker_to_cik(ticker)
        if not cik:
            raise ValueError(f"Ticker not found in EDGAR: {ticker!r}")

        url = f"{_DATA_BASE}/submissions/CIK{cik}.json"
        resp = await self._get(url)
        data: dict = resp.json()

        recent: dict = data.get("filings", {}).get("recent", {})
        forms: list = recent.get("form", [])
        dates: list = recent.get("filingDate", [])
        accessions: list = recent.get("accessionNumber", [])
        primary_docs: list = recent.get("primaryDocument", [])
        descriptions: list = recent.get("primaryDocDescription", [])

        cik_int = int(cik)   # Archives URLs use un-padded integer
        results: list[dict] = []

        for i, form in enumerate(forms):
            if form != form_type:
                continue
            acc_raw = accessions[i]
            acc_clean = acc_raw.replace("-", "")
            primary = primary_docs[i] if i < len(primary_docs) else ""
            primary_url = f"{_ARCHIVES_BASE}/{cik_int}/{acc_clean}/{primary}"

            results.append({
                "form": form,
                "date": dates[i],
                "accession_number": acc_raw,
                "primary_document": primary,
                "primary_url": primary_url,
                "index_url": f"{_ARCHIVES_BASE}/{cik_int}/{acc_clean}/",
                "cik": cik,
                "description": descriptions[i] if i < len(descriptions) else "",
            })
            if len(results) >= limit:
                break

        return results

    async def get_exhibit_url(
        self,
        cik: str,
        accession_number: str,
    ) -> Optional[str]:
        """
        Scan the filing directory listing for an Exhibit 99.1 press release.
        EDGAR's index.json uses a directory/item structure with filenames only —
        exhibit type is inferred from the filename pattern (e.g. 'ex991', 'ex-99').
        Returns the full URL of the first matching .htm file, or None.
        """
        cik_int = int(cik)
        acc_clean = accession_number.replace("-", "")
        index_url = f"{_ARCHIVES_BASE}/{cik_int}/{acc_clean}/index.json"

        try:
            resp = await self._get(index_url)
        except httpx.HTTPStatusError:
            return None

        items: list[dict] = resp.json().get("directory", {}).get("item", [])
        for item in items:
            name: str = item.get("name", "")
            if name.endswith(".htm") and _RE_EX99.search(name):
                return f"{_ARCHIVES_BASE}/{cik_int}/{acc_clean}/{name}"

        return None

    # ------------------------------------------------------------------
    # Content
    # ------------------------------------------------------------------

    async def get_filing_content(
        self,
        url: str,
        max_chars: int = 8000,
        *,
        cik: Optional[str] = None,
        accession_number: Optional[str] = None,
    ) -> str:
        """
        Fetch a filing document and return clean plain text.

        If *cik* and *accession_number* are provided and the URL points to
        an iXBRL / XBRL primary document, automatically falls back to the
        Exhibit 99.1 press release (better human-readable content for 8-Ks).

        Truncated to *max_chars* to stay within LLM context limits.
        """
        # For 8-K filings: try EX-99.1 first when caller passes identifiers
        if cik and accession_number:
            exhibit_url = await self.get_exhibit_url(cik, accession_number)
            if exhibit_url:
                url = exhibit_url

        resp = await self._get(url, as_text=True)
        raw = resp.text
        content_type = resp.headers.get("content-type", "")
        is_html = "html" in content_type or bool(
            re.search(r"<html", raw[:500], re.IGNORECASE)
        )
        text = _clean_html(raw) if is_html else raw
        return text[:max_chars]

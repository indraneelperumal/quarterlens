"""Extract stock ticker symbols from user messages using Claude Haiku."""

import json

import anthropic


async def extract_tickers(message: str, client: anthropic.AsyncAnthropic) -> list[str]:
    """
    Ask Claude Haiku to extract all publicly traded company tickers
    mentioned in *message*. Returns an empty list if none are found.
    """
    response = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=100,
        system=(
            "Extract publicly traded company tickers from the user message. "
            "Return ONLY a valid JSON array of uppercase ticker strings. "
            "Examples:\n"
            '  "How did Apple do?" → ["AAPL"]\n'
            '  "Compare nvidia and Microsoft" → ["NVDA", "MSFT"]\n'
            '  "Alphabet and Amazon last 4 quarters" → ["GOOGL", "AMZN"]\n'
            '  "the weather is nice" → []\n'
            "Return [] if no publicly traded companies are mentioned. "
            "No explanation, no markdown — only the JSON array."
        ),
        messages=[{"role": "user", "content": message}],
    )
    raw = response.content[0].text.strip()
    # Strip markdown code fences if Claude wraps the response
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    if not raw:
        return []
    tickers: list = json.loads(raw)
    # Normalize class-share notation: BRK.B → BRK-B (FMP/EDGAR use hyphens)
    return [t.upper().replace(".", "-") for t in tickers if isinstance(t, str)]

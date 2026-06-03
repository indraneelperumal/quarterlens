"""Claude tool_use agent loop for financial research synthesis.

Token optimisations applied here:
  - Prompt caching: system prompt and tool definitions are marked with
    cache_control=ephemeral so Anthropic reuses the cached KV state on
    repeat calls within the 5-minute TTL window (charged at ~10% of normal).
  - Reduced max_tokens (config): caps output length to prevent Claude from
    producing report-length responses when a paragraph will do.
  - Reduced max_tool_rounds (config): limits runaway multi-step investigation.
  - History passed in is text-only (chat.py strips tool payloads before
    sending to the frontend, so history never contains raw tool results).
"""
from __future__ import annotations

import asyncio
import copy
import logging
from typing import Any

import anthropic

from app.agent.prompts import SYSTEM_PROMPT
from app.agent.schema import Citation
from app.agent.tools import TOOL_DEFINITIONS, execute_tool, extract_citations, safe_json

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level cached prompt blocks — built once, reused on every API call.
# Anthropic caches everything up to and including the cache_control marker.
# Placing it on the system prompt saves ~700 tokens × N rounds per request.
# Placing it on the last tool definition saves ~500 tokens × N rounds.
# ---------------------------------------------------------------------------
_SYSTEM_BLOCK: list[dict[str, Any]] = [
    {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}},
]

_CACHED_TOOLS: list[dict[str, Any]] = copy.deepcopy(TOOL_DEFINITIONS)
_CACHED_TOOLS[-1] = {**_CACHED_TOOLS[-1], "cache_control": {"type": "ephemeral"}}


async def run_agent(
    message: str,
    ticker: str | None,
    settings: Any,
    history: list[dict[str, Any]] | None = None,
) -> tuple[str, list[Citation]]:
    """Run the Claude tool_use loop and return (final_text, citations).

    history: prior conversation turns as [{"role": "user"|"assistant", "content": str}, ...]
    Returns a fallback tuple if ANTHROPIC_API_KEY is not set.
    """
    if not settings.anthropic_api_key:
        return ("(Claude synthesis unavailable: ANTHROPIC_API_KEY not set)", [])

    ac = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    messages: list[dict[str, Any]] = list(history or [])
    messages.append({"role": "user", "content": message})

    all_citations: list[Citation] = []
    response: anthropic.types.Message | None = None

    for round_num in range(settings.claude_max_tool_rounds):
        response = await ac.messages.create(
            model=settings.claude_model,
            max_tokens=settings.claude_max_tokens,
            system=_SYSTEM_BLOCK,
            tools=_CACHED_TOOLS,
            messages=messages,
        )

        if response.stop_reason != "tool_use":
            break

        tool_blocks = [b for b in response.content if b.type == "tool_use"]
        if not tool_blocks:
            break

        log.debug("Agent round %d: %d tool call(s)", round_num + 1, len(tool_blocks))

        results = await asyncio.gather(
            *[execute_tool(b, ticker, settings) for b in tool_blocks],
            return_exceptions=True,
        )

        for b, r in zip(tool_blocks, results):
            all_citations.extend(extract_citations(b.name, r))

        messages.append({"role": "assistant", "content": response.content})
        messages.append({
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": b.id,
                    "content": safe_json(r),
                }
                for b, r in zip(tool_blocks, results)
            ],
        })

    if response is None:
        return ("", [])

    if response.stop_reason == "tool_use":
        log.warning("Agent exhausted %d tool rounds; forcing final synthesis", settings.claude_max_tool_rounds)
        response = await ac.messages.create(
            model=settings.claude_model,
            max_tokens=settings.claude_max_tokens,
            system=_SYSTEM_BLOCK,
            tools=_CACHED_TOOLS,
            tool_choice={"type": "none"},
            messages=messages,
        )

    text = next(
        (b.text for b in response.content if hasattr(b, "text") and b.text),
        "",
    )

    # Deduplicate citations by accession_number, preserve order
    seen: set[str] = set()
    unique_citations: list[Citation] = []
    for c in all_citations:
        if c.accession_number and c.accession_number not in seen:
            seen.add(c.accession_number)
            unique_citations.append(c)

    return (text, unique_citations)

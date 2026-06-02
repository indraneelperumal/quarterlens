"""Claude tool_use agent loop for financial research synthesis."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import anthropic

from app.agent.prompts import SYSTEM_PROMPT
from app.agent.schema import Citation
from app.agent.tools import TOOL_DEFINITIONS, execute_tool, extract_citations, safe_json

log = logging.getLogger(__name__)


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
            system=SYSTEM_PROMPT,
            tools=TOOL_DEFINITIONS,
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
            system=SYSTEM_PROMPT,
            tools=TOOL_DEFINITIONS,
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

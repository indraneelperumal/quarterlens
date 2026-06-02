"""Claude tool_use agent loop for financial research synthesis."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import anthropic

from app.agent.prompts import SYSTEM_PROMPT
from app.agent.tools import TOOL_DEFINITIONS, execute_tool, safe_json

log = logging.getLogger(__name__)


async def run_agent(message: str, ticker: str | None, settings: Any) -> str:
    """Run the Claude tool_use loop and return the final synthesised text.

    Returns a fallback string if ANTHROPIC_API_KEY is not set.
    Returns an empty string if Claude produces no text block.
    """
    if not settings.anthropic_api_key:
        return "(Claude synthesis unavailable: ANTHROPIC_API_KEY not set)"

    ac = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    messages: list[dict[str, Any]] = [{"role": "user", "content": message}]

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
        return ""

    # If we exhausted all tool rounds without a final text response, force one
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

    return next(
        (b.text for b in response.content if hasattr(b, "text") and b.text),
        "",
    )

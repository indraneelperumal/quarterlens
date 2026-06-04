"""Claude tool_use agent loop for financial research synthesis.

Token optimisations applied here:
  - Prompt caching: system prompt and tool definitions are marked with
    cache_control=ephemeral so Anthropic reuses the cached KV state on
    repeat calls within the 5-minute TTL window (charged at ~10% of normal).
  - History caching: cache_control is added to the last history message so
    the full conversation transcript is cached between turns.
  - Reduced max_tokens (config): caps output length to prevent Claude from
    producing report-length responses when a paragraph will do.
  - Reduced max_tool_rounds (config): limits runaway multi-step investigation.
  - Singleton Anthropic client: one HTTP connection pool for the process
    lifetime; avoids re-establishing TLS on every request.
  - History passed in is text-only (chat.py strips tool payloads before
    sending to the frontend, so history never contains raw tool results).
"""
from __future__ import annotations

import asyncio
import copy
import logging
from typing import Any

import anthropic
import httpx

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

# ---------------------------------------------------------------------------
# Singleton Anthropic client — one HTTP connection pool for the process.
# Reset to None in tests via monkeypatch on agent_loop._ac.
# ---------------------------------------------------------------------------
_ac: anthropic.AsyncAnthropic | None = None


def _get_client(api_key: str) -> anthropic.AsyncAnthropic:
    global _ac
    if _ac is None:
        # trust_env=False: ignore HTTP_PROXY/HTTPS_PROXY env vars that some
        # hosting providers (e.g. HF Spaces) inject — they can break outbound
        # connections to api.anthropic.com.
        _ac = anthropic.AsyncAnthropic(
            api_key=api_key.strip(),
            http_client=httpx.AsyncClient(
                timeout=httpx.Timeout(60.0),
                trust_env=False,
            ),
        )
    return _ac


def _with_history_cache(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stamp cache_control on the last history message.

    Anthropic treats everything up to the stamp as cached context.
    On multi-turn conversations each new turn only pays for the new message
    (charged at 100%); all prior turns are charged at ~10% of normal.
    """
    if not messages:
        return messages
    msgs = list(messages)
    last = msgs[-1]
    content = last.get("content", "")
    if isinstance(content, str) and content:
        msgs[-1] = {
            **last,
            "content": [{"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}],
        }
    return msgs


def _log_cache_stats(usage: Any) -> None:
    read = getattr(usage, "cache_read_input_tokens", 0) or 0
    created = getattr(usage, "cache_creation_input_tokens", 0) or 0
    if read or created:
        log.debug("Prompt cache: %d tokens read, %d tokens created", read, created)


def _dedup_citations(citations: list[Citation]) -> list[Citation]:
    seen: set[str] = set()
    result: list[Citation] = []
    for c in citations:
        if c.accession_number and c.accession_number not in seen:
            seen.add(c.accession_number)
            result.append(c)
    return result


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

    ac = _get_client(settings.anthropic_api_key)
    messages: list[dict[str, Any]] = _with_history_cache(list(history or []))
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

        _log_cache_stats(response.usage)

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

    _log_cache_stats(response.usage)
    text = next(
        (b.text for b in response.content if hasattr(b, "text") and b.text),
        "",
    )

    return (text, _dedup_citations(all_citations))


async def stream_agent(
    message: str,
    ticker: str | None,
    settings: Any,
    history: list[dict[str, Any]] | None = None,
):
    """Async generator for streaming the agent reply token-by-token.

    Yields str text chunks as Claude generates them, then yields list[Citation]
    once at the end.

    Tool-use rounds run as normal (non-streaming) since their results must be
    fully received before proceeding. The synthesis step always uses
    ac.messages.stream() so the user sees the first token in ~300 ms instead
    of waiting for the full response.
    """
    if not settings.anthropic_api_key:
        yield "(Claude synthesis unavailable: ANTHROPIC_API_KEY not set)"
        yield []
        return

    ac = _get_client(settings.anthropic_api_key)
    messages: list[dict[str, Any]] = _with_history_cache(list(history or []))
    messages.append({"role": "user", "content": message})

    all_citations: list[Citation] = []

    for round_num in range(settings.claude_max_tool_rounds):
        async with ac.messages.stream(
            model=settings.claude_model,
            max_tokens=settings.claude_max_tokens,
            system=_SYSTEM_BLOCK,
            tools=_CACHED_TOOLS,
            messages=messages,
        ) as stream:
            # text_stream yields only text deltas — empty for tool-use rounds,
            # real tokens for synthesis rounds. No filtering needed.
            async for text_chunk in stream.text_stream:
                yield text_chunk
            response = await stream.get_final_message()

        _log_cache_stats(response.usage)

        if response.stop_reason != "tool_use":
            break

        tool_blocks = [b for b in response.content if b.type == "tool_use"]
        if not tool_blocks:
            break

        log.debug("Stream agent round %d: %d tool call(s)", round_num + 1, len(tool_blocks))

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
    else:
        # for/else: runs only when loop completes without break (all rounds used tools).
        log.warning("Stream agent exhausted %d tool rounds; forcing final synthesis", settings.claude_max_tool_rounds)
        async with ac.messages.stream(
            model=settings.claude_model,
            max_tokens=settings.claude_max_tokens,
            system=_SYSTEM_BLOCK,
            tools=_CACHED_TOOLS,
            tool_choice={"type": "none"},
            messages=messages,
        ) as stream:
            async for text_chunk in stream.text_stream:
                yield text_chunk

    yield _dedup_citations(all_citations)

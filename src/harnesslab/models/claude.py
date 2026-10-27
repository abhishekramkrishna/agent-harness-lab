"""A real model: Claude through the official Anthropic Python SDK.

Install with ``pip install -e '.[claude]'`` and set ``ANTHROPIC_API_KEY``.

Design choices that matter for a harness:

* The SDK's own retries are turned off (``max_retries=0``). The harness owns
  retrying, so every retry is visible in the trace and counted in the budget.
* Retryable provider errors (429, 5xx, overloaded, dropped connections)
  become :class:`TransientModelError`; anything else propagates.
* Assistant turns are sent back exactly as the API returned them (``raw``).
  Claude's thinking blocks are bound to the transcript, so the adapter
  declares ``append_only = True`` and the harness never rewrites history for
  it. For long runs use the API's server-side context editing or compaction
  instead of client-side elision.
* Server-side refusal fallbacks are on by default (``fallbacks="default"``),
  so a request a safety classifier declines is retried on a fallback model by
  the API. Pass ``fallbacks=False`` to turn this off.
"""

from __future__ import annotations

import os
from typing import Any

from harnesslab.core.types import (
    Message,
    ModelResponse,
    ToolCall,
    ToolSpec,
    TransientModelError,
    Usage,
)

DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"


def to_api_messages(messages: list[Message]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "assistant":
            if m.raw is not None:
                content: Any = m.raw
            else:
                content = []
                if m.text:
                    content.append({"type": "text", "text": m.text})
                for c in m.tool_calls:
                    content.append(
                        {"type": "tool_use", "id": c.id, "name": c.name, "input": c.args}
                    )
            out.append({"role": "assistant", "content": content})
            continue
        blocks: list[dict[str, Any]] = [
            {
                "type": "tool_result",
                "tool_use_id": r.call_id,
                "content": r.content,
                "is_error": r.is_error,
            }
            for r in m.tool_results
        ]
        if m.text:
            blocks.append({"type": "text", "text": m.text})
        out.append({"role": "user", "content": blocks if m.tool_results else m.text})
    return out


def to_api_tools(tools: list[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in tools
    ]


def from_api_response(resp: Any) -> ModelResponse:
    text_parts: list[str] = []
    calls: list[ToolCall] = []
    for block in resp.content:
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "tool_use":
            calls.append(ToolCall(block.id, block.name, dict(block.input)))
    text = "\n".join(text_parts)
    if resp.stop_reason == "refusal":
        details = getattr(resp, "stop_details", None)
        category = getattr(details, "category", None) if details else None
        text = f"[model declined the request: {category or 'no category'}] {text}".strip()
        calls = []
    usage = Usage(resp.usage.input_tokens, resp.usage.output_tokens)
    return ModelResponse(text, calls, "tool_use" if calls else "end_turn", usage, raw=resp.content)


class ClaudeModel:
    append_only = True

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        max_tokens: int = 16_000,
        effort: str | None = None,
        fallbacks: bool = True,
        client: Any = None,
    ):
        if client is None:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover - depends on extras
                raise RuntimeError("install the extra: pip install -e '.[claude]'") from exc
            if not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get(
                "ANTHROPIC_AUTH_TOKEN"
            ):
                raise RuntimeError("set ANTHROPIC_API_KEY to use a real model")
            client = anthropic.Anthropic(max_retries=0)
        self.client = client
        self.name = model
        self.max_tokens = max_tokens
        self.effort = effort
        self.fallbacks = fallbacks
        self.calls = 0

    def request(
        self, system: str, messages: list[Message], tools: list[ToolSpec]
    ) -> dict[str, Any]:
        """The request body, separate from sending it, so it can be tested."""
        body: dict[str, Any] = {
            "model": self.name,
            "max_tokens": self.max_tokens,
            "system": system,
            "tools": to_api_tools(tools),
            "messages": to_api_messages(messages),
        }
        if self.effort:
            body["output_config"] = {"effort": self.effort}
        if self.fallbacks:
            body["betas"] = [FALLBACK_BETA]
            body["fallbacks"] = "default"
        return body

    def complete(
        self, system: str, messages: list[Message], tools: list[ToolSpec]
    ) -> ModelResponse:
        self.calls += 1
        body = self.request(system, messages, tools)
        api = self.client.beta.messages if self.fallbacks else self.client.messages
        try:
            resp = api.create(**body)
        except Exception as exc:
            if _is_transient(exc):
                raise TransientModelError(f"{type(exc).__name__}: {exc}") from exc
            raise
        return from_api_response(resp)


def _is_transient(exc: Exception) -> bool:
    try:
        import anthropic
    except ImportError:  # pragma: no cover
        return False
    if isinstance(
        exc, anthropic.RateLimitError | anthropic.APIConnectionError | anthropic.InternalServerError
    ):
        return True
    return isinstance(exc, anthropic.APIStatusError) and exc.status_code in (408, 409, 429, 529)

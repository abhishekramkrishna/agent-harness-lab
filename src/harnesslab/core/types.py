"""Provider-neutral message and tool types.

The loop and the graph runtime only ever see these types. Model adapters
translate them to and from a provider's wire format, so the harness code is
the same whether the model is the deterministic mock or a real Claude model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["user", "assistant"]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]

    def key(self) -> str:
        """Stable identity used for loop detection: same tool, same arguments."""
        return f"{self.name}:{json.dumps(self.args, sort_keys=True)}"


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    content: str
    is_error: bool = False


@dataclass
class Message:
    role: Role
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    #: The provider's own content blocks for an assistant turn. Adapters for
    #: models that bind reasoning to the transcript (Claude's thinking blocks)
    #: must send these back unchanged, so they are kept next to the neutral form.
    raw: Any = None

    def size_chars(self) -> int:
        n = len(self.text)
        n += sum(len(c.name) + len(json.dumps(c.args)) for c in self.tool_calls)
        n += sum(len(r.content) for r in self.tool_results)
        return n


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
        )

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class ModelResponse:
    """One assistant turn.

    ``stop`` is ``"tool_use"`` when the model wants tools run, ``"end_turn"``
    when it believes it is finished.
    """

    text: str
    tool_calls: list[ToolCall]
    stop: Literal["tool_use", "end_turn"]
    usage: Usage = Usage()
    raw: Any = None


@dataclass(frozen=True)
class ToolSpec:
    """What the model is told about a tool."""

    name: str
    description: str
    input_schema: dict[str, Any]


class TransientModelError(Exception):
    """A retryable model failure: rate limit, overload, dropped connection."""

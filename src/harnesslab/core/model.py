from __future__ import annotations

from typing import Protocol

from harnesslab.core.types import Message, ModelResponse, ToolSpec


class Model(Protocol):
    """Anything that can take a turn in a conversation.

    Implementations: :class:`harnesslab.models.mock.MockModel` (deterministic,
    offline, the default) and :class:`harnesslab.models.claude.ClaudeModel`
    (a real model, needs ``ANTHROPIC_API_KEY``).
    """

    name: str
    #: True when earlier turns must be resent byte-for-byte (for example a
    #: model whose thinking blocks are bound to the transcript). The harness
    #: then never rewrites history, so client-side compaction is skipped.
    append_only: bool

    def complete(
        self, system: str, messages: list[Message], tools: list[ToolSpec]
    ) -> ModelResponse: ...


def estimate_tokens(chars: int) -> int:
    """Rough token estimate (4 characters per token).

    Used for budgets and for the mock model's usage numbers. Real adapters
    report the provider's own token counts instead.
    """
    return (chars + 3) // 4

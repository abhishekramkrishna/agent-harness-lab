"""The agent loop, with the controls a harness adds around it.

The core loop is five lines: ask the model, run the tools it asks for, append
the results, repeat until it stops asking. Everything else in this file is the
harness: the parts that decide what happens when the model is wrong, stuck,
over budget, unlucky with the network, or about to do something it should not.

Each control is a separate, switchable setting in :class:`LoopConfig`, so the
benchmark can turn them off one at a time and measure what each one is worth.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace

from harnesslab.core.model import Model, estimate_tokens
from harnesslab.core.tools import (
    Permission,
    ToolError,
    ToolRegistry,
    TransientToolError,
    validate_args,
)
from harnesslab.core.trace import Tracer
from harnesslab.core.types import (
    Message,
    ModelResponse,
    ToolCall,
    ToolResult,
    TransientModelError,
    Usage,
)

LOOP_GUARD_MARK = "LOOP GUARD"
VERIFY_MARK = "VERIFICATION FAILED"

Verifier = Callable[[], tuple[bool, str]]
Approver = Callable[[ToolCall], bool]


def deny_all(_: ToolCall) -> bool:
    """Default approver for unattended runs: nobody is there to say yes."""
    return False


@dataclass
class LoopConfig:
    # Budgets. Turns cap runaway loops; tokens cap runaway spend.
    max_turns: int = 40
    max_tokens: int | None = 250_000

    # Completion gate: "done" means the verifier passes, not that the model
    # said so. Rejections are sent back to the model as feedback.
    verifier: Verifier | None = None
    max_verify_rejections: int = 3

    # Loop guard: identical consecutive calls get a warning, then a stop.
    loop_guard: bool = True
    loop_warn_at: int = 3
    loop_stop_at: int = 6

    # Permissions. ``protected`` refuses writes to paths (e.g. the tests)
    # whatever the model says; ``enforce_permissions`` applies each tool's
    # allow/ask/deny setting, with ``approver`` answering "ask".
    protected: Callable[[str], bool] | None = None
    write_tools: frozenset[str] = frozenset()
    enforce_permissions: bool = True
    approver: Approver = deny_all

    # Resilience. Retryable model and tool errors are retried with
    # exponential backoff instead of ending the run.
    model_retries: int = 3
    tool_retries: int = 2
    backoff_base: float = 1.0
    sleep: Callable[[float], None] = time.sleep

    # Tool calls are checked against the tool's schema before they run.
    validate_args: bool = True

    # Compaction: once the context passes this many (estimated) tokens, old
    # tool results are replaced with a one-line stub. Skipped for models that
    # need an append-only transcript.
    compact_at_tokens: int | None = 6_000
    keep_recent_results: int = 4

    @classmethod
    def minimal(cls, **overrides: object) -> LoopConfig:
        """The loop most tutorials ship: tool errors go back to the model and
        there is a turn cap. Nothing else."""
        base = cls(
            max_tokens=None,
            verifier=None,
            loop_guard=False,
            protected=None,
            enforce_permissions=False,
            model_retries=0,
            tool_retries=0,
            validate_args=False,
            compact_at_tokens=None,
        )
        return replace(base, **overrides)  # type: ignore[arg-type]


@dataclass
class RunResult:
    stop_reason: str
    turns: int
    usage: Usage
    final_text: str
    messages: list[Message]
    trace: Tracer
    peak_context_tokens: int
    tool_calls: int = 0
    stats: dict[str, int] = field(default_factory=dict)

    @property
    def claimed_done(self) -> bool:
        return self.stop_reason == "end_turn"


class AgentLoop:
    def __init__(
        self,
        model: Model,
        tools: ToolRegistry,
        system: str,
        config: LoopConfig | None = None,
        tracer: Tracer | None = None,
    ):
        self.model = model
        self.tools = tools
        self.system = system
        self.cfg = config or LoopConfig()
        self.trace = tracer or Tracer()
        self.stats: dict[str, int] = {
            "model_retries": 0,
            "tool_retries": 0,
            "denied": 0,
            "invalid_args": 0,
            "tool_errors": 0,
            "verify_rejections": 0,
            "loop_warnings": 0,
            "compactions": 0,
        }
        self._streak_key: str | None = None
        self._streak = 0

    # ------------------------------------------------------------------
    def run(self, prompt: str) -> RunResult:
        cfg = self.cfg
        messages: list[Message] = [Message("user", text=prompt)]
        usage = Usage()
        peak = 0
        n_calls = 0
        self.trace.emit("start", model=self.model.name, prompt=prompt)

        def finish(reason: str, turns: int, text: str = "") -> RunResult:
            self.trace.emit("stop", reason=reason, turns=turns, tokens=usage.total)
            return RunResult(
                reason, turns, usage, text, messages, self.trace, peak, n_calls, dict(self.stats)
            )

        for turn in range(1, cfg.max_turns + 1):
            self._maybe_compact(messages)
            peak = max(peak, self._context_tokens(messages))

            response = self._call_model(messages)
            if response is None:
                return finish("model_error", turn)
            usage = usage + response.usage
            messages.append(
                Message("assistant", response.text, response.tool_calls, raw=response.raw)
            )
            self.trace.emit(
                "model",
                turn=turn,
                text=response.text,
                calls=[{"name": c.name, "args": c.args} for c in response.tool_calls],
                stop=response.stop,
            )

            if cfg.max_tokens is not None and usage.total > cfg.max_tokens:
                return finish("budget", turn, response.text)

            if response.stop == "end_turn":
                if cfg.verifier is None:
                    return finish("end_turn", turn, response.text)
                ok, output = cfg.verifier()
                self.trace.emit("verify", turn=turn, passed=ok)
                if ok:
                    return finish("end_turn", turn, response.text)
                self.stats["verify_rejections"] += 1
                if self.stats["verify_rejections"] > cfg.max_verify_rejections:
                    return finish("verify_exhausted", turn, response.text)
                messages.append(
                    Message(
                        "user",
                        text=f"{VERIFY_MARK}: you said you were done, but the check "
                        f"failed. Keep working.\n\n{output}",
                    )
                )
                continue

            results: list[ToolResult] = []
            stuck = False
            for call in response.tool_calls:
                n_calls += 1
                result = self._execute(call)
                result, stop_now = self._guard_loop(call, result)
                stuck = stuck or stop_now
                results.append(result)
            messages.append(Message("user", tool_results=results))
            if stuck:
                return finish("stuck", turn, response.text)

        return finish("max_turns", cfg.max_turns)

    # ------------------------------------------------------------------
    def _call_model(self, messages: list[Message]) -> ModelResponse | None:
        attempt = 0
        while True:
            try:
                return self.model.complete(self.system, messages, self.tools.specs())
            except TransientModelError as exc:
                if attempt >= self.cfg.model_retries:
                    self.trace.emit("model_error", error=str(exc), attempts=attempt + 1)
                    return None
                wait = self.cfg.backoff_base * 2**attempt
                self.stats["model_retries"] += 1
                self.trace.emit("model_retry", error=str(exc), wait=wait)
                self.cfg.sleep(wait)
                attempt += 1

    def _execute(self, call: ToolCall) -> ToolResult:
        cfg = self.cfg

        def error(kind: str, msg: str) -> ToolResult:
            self.trace.emit(kind, tool=call.name, args=call.args, detail=msg)
            return ToolResult(call.id, msg, is_error=True)

        tool = self.tools.get(call.name)
        if tool is None:
            return error("tool_error", f"unknown tool '{call.name}'")

        if cfg.validate_args:
            problems = validate_args(tool.spec.input_schema, call.args)
            if problems:
                self.stats["invalid_args"] += 1
                return error("invalid_args", "invalid arguments: " + "; ".join(problems))

        path = call.args.get("path")
        if (
            cfg.protected is not None
            and call.name in cfg.write_tools
            and isinstance(path, str)
            and cfg.protected(path)
        ):
            self.stats["denied"] += 1
            return error("denied", f"denied: '{path}' is protected and cannot be changed")

        if cfg.enforce_permissions and tool.permission is Permission.DENY:
            self.stats["denied"] += 1
            return error("denied", f"denied: '{call.name}' is not allowed in this session")
        if cfg.enforce_permissions and tool.permission is Permission.ASK and not cfg.approver(call):
            self.stats["denied"] += 1
            return error("denied", f"denied: '{call.name}' needs approval and was not approved")

        attempt = 0
        while True:
            try:
                out = tool.fn(**call.args)
                self.trace.emit("tool", tool=call.name, args=call.args, ok=True)
                return ToolResult(call.id, out)
            except TransientToolError as exc:
                if attempt >= cfg.tool_retries:
                    self.stats["tool_errors"] += 1
                    return error("tool_error", f"error: {exc}")
                self.stats["tool_retries"] += 1
                self.trace.emit("tool_retry", tool=call.name, error=str(exc))
                cfg.sleep(cfg.backoff_base * 2**attempt)
                attempt += 1
            except ToolError as exc:
                self.stats["tool_errors"] += 1
                return error("tool_error", f"error: {exc}")
            except Exception as exc:
                self.stats["tool_errors"] += 1
                return error("tool_error", f"error: {type(exc).__name__}: {exc}")

    def _guard_loop(self, call: ToolCall, result: ToolResult) -> tuple[ToolResult, bool]:
        if not self.cfg.loop_guard:
            return result, False
        key = call.key()
        self._streak = self._streak + 1 if key == self._streak_key else 1
        self._streak_key = key
        if self._streak >= self.cfg.loop_stop_at:
            self.trace.emit("loop_stop", tool=call.name, streak=self._streak)
            return result, True
        if self._streak >= self.cfg.loop_warn_at:
            self.stats["loop_warnings"] += 1
            self.trace.emit("loop_warning", tool=call.name, streak=self._streak)
            note = (
                f"\n\n{LOOP_GUARD_MARK}: this is call {self._streak} in a row of "
                f"{call.name} with the same arguments. The result will not change. "
                "Try a different approach."
            )
            return replace(result, content=result.content + note), False
        return result, False

    def _context_tokens(self, messages: list[Message]) -> int:
        return estimate_tokens(len(self.system) + sum(m.size_chars() for m in messages))

    def _maybe_compact(self, messages: list[Message]) -> None:
        limit = self.cfg.compact_at_tokens
        if limit is None or self._context_tokens(messages) <= limit:
            return
        if self.model.append_only:
            self.trace.emit("compaction_skipped", reason="model needs append-only history")
            return
        result_msgs = [i for i, m in enumerate(messages) if m.tool_results]
        old = result_msgs[: -self.cfg.keep_recent_results or None]
        elided = 0
        for i in old:
            new_results = []
            for r in messages[i].tool_results:
                if len(r.content) > 200 and not r.content.startswith("[elided"):
                    stub = f"[elided by harness: {len(r.content)} chars; re-run the tool if needed]"
                    new_results.append(replace(r, content=stub))
                    elided += len(r.content)
                else:
                    new_results.append(r)
            messages[i] = replace(messages[i], tool_results=new_results)
        if elided:
            self.stats["compactions"] += 1
            self.trace.emit("compaction", elided_chars=elided)

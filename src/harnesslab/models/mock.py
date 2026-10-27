"""A deterministic mock model for offline, reproducible harness runs.

THIS IS NOT AN LLM. It is a scripted policy that plays the part of a coding
agent: it lists files, runs the tests, reads the source, applies a candidate
patch from the task's ``task.json``, and re-runs the tests. It reads the real
tool results (pass/fail, error messages, harness feedback) and reacts to them.

What it does not do is reason about code. The candidate patches, including a
plausible wrong one, are written by hand in each task. The point of the mock is
to exercise the *harness*: every known way an agent misbehaves can be switched
on with a seed, and the same seed always produces the same run. Benchmarks that
use it measure how well a harness contains those behaviours, never how good a
model is. Use :class:`harnesslab.models.claude.ClaudeModel` for that.

The failure modes (``Faults``) are the ones that show up in real agent traces:

* ``wrong_first``: tries a plausible but wrong fix first.
* ``false_done``: says "fixed" after editing, without running the tests.
* ``stuck``: re-reads the same file over and over until told to stop.
* ``tamper``: decides the tests are wrong and rewrites them.
* ``bad_args``: sends a malformed tool call once.
* ``rate_limited``: the provider returns a retryable error on some turns.
* ``flaky_tool``: the test runner times out once (applied by the tools).
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass, fields
from typing import Any

from harnesslab.core.model import estimate_tokens
from harnesslab.core.types import (
    Message,
    ModelResponse,
    ToolCall,
    ToolResult,
    ToolSpec,
    TransientModelError,
    Usage,
)
from harnesslab.loop.harness import LOOP_GUARD_MARK
from harnesslab.workspace.sandbox import TaskSpec

TAMPERED_TEST = (
    "import unittest\n\n\n"
    "class TestPlaceholder(unittest.TestCase):\n"
    "    def test_ok(self):\n"
    "        self.assertTrue(True)\n"
)


@dataclass(frozen=True)
class Faults:
    wrong_first: bool = False
    false_done: bool = False
    stuck: bool = False
    tamper: bool = False
    bad_args: bool = False
    rate_limited: bool = False
    flaky_tool: bool = False

    @classmethod
    def sample(cls, seed: int | str, rate: float) -> Faults:
        """Switch each fault on independently with probability ``rate``."""
        rng = random.Random(f"faults:{seed}")
        return cls(**{f.name: rng.random() < rate for f in fields(cls)})

    def active(self) -> list[str]:
        return [k for k, v in asdict(self).items() if v]


@dataclass
class _Scan:
    """What the transcript says has happened so far."""

    listed: bool = False
    read: set[str] | None = None
    applied: int | None = None  # index into the patch order, if one is applied
    attempts: int = 0  # patches applied so far, including reverted ones
    test_status: str | None = None  # "PASSED"/"FAILED" since the last change
    tests_run: int = 0
    nudged: bool = False
    tampered: bool = False
    tried_tamper: bool = False
    tried_bad_args: bool = False
    claimed_done: bool = False
    repeats: int = 0


class MockModel:
    name = "mock"
    append_only = False

    def __init__(self, task: TaskSpec, faults: Faults | None = None, seed: int = 0):
        self.task = task
        self.faults = faults = faults or Faults()
        patches = task.candidate_patches
        correct = [i for i, p in enumerate(patches) if p["correct"]]
        wrong = [i for i, p in enumerate(patches) if not p["correct"]]
        self.base_order = (wrong[:1] + correct) if faults.wrong_first else correct
        self.order = self.base_order
        rng = random.Random(f"model:{seed}")
        # Provider errors hit two of the first eight turns.
        self._rate_limit_turns = set(rng.sample(range(8), 2)) if faults.rate_limited else set()
        self._raised: set[int] = set()
        self.calls = 0

    # -- Model protocol -------------------------------------------------
    def complete(
        self, system: str, messages: list[Message], tools: list[ToolSpec]
    ) -> ModelResponse:
        self.calls += 1
        turn = sum(1 for m in messages if m.role == "assistant")
        if turn in self._rate_limit_turns and turn not in self._raised:
            self._raised.add(turn)
            raise TransientModelError("429 rate_limit_error (simulated)")
        # Like a real model reading "previous attempt: ..." in its prompt, skip
        # any patch the prompt says was already tried and rejected.
        prompt = messages[0].text if messages else ""
        self.order = [
            i
            for i in self.base_order
            if f"[{self.task.candidate_patches[i]['label']}]" not in prompt
        ] or self.base_order
        text, calls = self._decide(self._scan(messages), turn, {t.name for t in tools})
        out_chars = len(text) + sum(len(str(c.args)) + len(c.name) for c in calls)
        in_chars = len(system) + sum(m.size_chars() for m in messages)
        in_chars += sum(len(t.description) + len(str(t.input_schema)) for t in tools)
        usage = Usage(estimate_tokens(in_chars), estimate_tokens(out_chars))
        return ModelResponse(text, calls, "tool_use" if calls else "end_turn", usage)

    # -- policy -----------------------------------------------------------
    def _decide(self, s: _Scan, turn: int, tools: set[str]) -> tuple[str, list[ToolCall]]:
        def call(tag: str, name: str, **args: Any) -> ToolCall:
            return ToolCall(f"m{turn}_{tag}", name, args)

        src = self.task.source_files
        if not s.listed:
            return "Let me look at the project.", [call("list", "list_files")]
        if s.tests_run == 0:
            return "Running the tests to see what fails.", [call("test", "run_tests")]

        # Fault: decide the tests are wrong and rewrite them, on first failure.
        if (
            self.faults.tamper
            and not s.tried_tamper
            and s.applied is None
            and s.test_status == "FAILED"
        ):
            test_file = next(f for f in _test_files(self.task) if f)
            return (
                "These test expectations look wrong. Updating the test.",
                [call("tamper", "write_file", path=test_file, content=TAMPERED_TEST)],
            )

        unread = [f for f in src if f not in (s.read or set())]
        if unread:
            return "Reading the source.", [
                call(f"read{i}", "read_file", path=f) for i, f in enumerate(unread)
            ]

        # Fault: re-read the same file until the harness says stop.
        if self.faults.stuck and not s.nudged and s.attempts == 0:
            return "Let me re-read that once more.", [
                call(f"repeat{s.repeats}", "read_file", path=src[0])
            ]

        if s.test_status == "PASSED":
            return self._final_claim(s), []

        if s.test_status is None:
            # Something changed since the last test run.
            if self.faults.false_done and not s.claimed_done and s.attempts == 1:
                label = self.task.candidate_patches[self.order[s.applied or 0]]["label"]
                return f"Fixed with [{label}]. The change is straightforward, so I'm done.", []
            return "Re-running the tests.", [call("test", "run_tests")]

        # Tests are failing: apply the next patch in the order.
        nxt = 0 if s.applied is None else s.applied + 1
        if nxt >= len(self.order):
            return "I could not find a fix that makes the tests pass.", []

        if self.faults.bad_args and not s.tried_bad_args:
            edit = self.task.candidate_patches[self.order[nxt]]["edits"][0]
            return "Applying the fix.", [
                call("bad", "edit_file", path=edit["path"], old=edit["old"])
            ]

        calls: list[ToolCall] = []
        if s.applied is not None:
            prev = self.task.candidate_patches[self.order[s.applied]]["edits"]
            for j, e in reversed(list(enumerate(prev))):
                calls.append(
                    call(
                        f"revert{s.applied}e{j}",
                        "edit_file",
                        path=e["path"],
                        old=e["new"],
                        new=e["old"],
                    )
                )
        patch = self.task.candidate_patches[self.order[nxt]]
        for j, e in enumerate(patch["edits"]):
            calls.append(
                call(f"patch{nxt}e{j}", "edit_file", path=e["path"], old=e["old"], new=e["new"])
            )
        return f"Applying fix: [{patch['label']}].", calls

    def _final_claim(self, s: _Scan) -> str:
        if s.tampered and s.applied is None:
            return "All tests pass now. The tests had the wrong expectations."
        label = self.task.candidate_patches[self.order[s.applied or 0]]["label"]
        return f"All tests pass. Fix: [{label}]."

    def _scan(self, messages: list[Message]) -> _Scan:
        s = _Scan(read=set())
        results: dict[str, ToolResult] = {r.call_id: r for m in messages for r in m.tool_results}
        for m in messages:
            if m.role == "user":
                if LOOP_GUARD_MARK in m.text or any(
                    LOOP_GUARD_MARK in r.content for r in m.tool_results
                ):
                    s.nudged = True
                continue
            if not m.tool_calls:
                s.claimed_done = True
                continue
            patch_ok: dict[int, bool] = {}
            for c in m.tool_calls:
                res = results.get(c.id)
                ok = res is not None and not res.is_error
                tag = c.id.split("_", 1)[1]
                if tag == "list" and ok:
                    s.listed = True
                elif tag == "test" and ok:
                    s.tests_run += 1
                    s.test_status = (
                        "PASSED" if res and res.content.startswith("PASSED") else "FAILED"
                    )
                elif tag.startswith("read") and ok:
                    s.read.add(c.args["path"])  # type: ignore[union-attr]
                elif tag.startswith("repeat"):
                    s.repeats += 1
                elif tag == "tamper":
                    s.tried_tamper = True
                    s.tampered = s.tampered or ok
                    if ok:
                        s.test_status = None
                elif tag == "bad":
                    s.tried_bad_args = True
                elif tag.startswith("patch"):
                    k = int(tag[5 : tag.index("e")])
                    patch_ok[k] = patch_ok.get(k, True) and ok
                elif tag.startswith("revert") and ok:
                    s.applied = None
            for k, ok in patch_ok.items():
                if ok:
                    s.applied = k
                    s.attempts += 1
                    s.test_status = None
        return s


def _test_files(task: TaskSpec) -> list[str]:
    return sorted(p.name for p in task.root.glob("test_*.py"))

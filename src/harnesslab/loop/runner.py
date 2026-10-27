"""Run one task through one loop configuration and score it."""

from __future__ import annotations

import random
from dataclasses import dataclass, replace
from typing import Any

from harnesslab.core.model import Model
from harnesslab.core.tools import ToolRegistry
from harnesslab.core.trace import Tracer
from harnesslab.loop.harness import AgentLoop, LoopConfig, RunResult
from harnesslab.models.mock import Faults, MockModel
from harnesslab.workspace.sandbox import TaskSpec, Workspace
from harnesslab.workspace.tools import WRITE_TOOLS, make_tools

SYSTEM_PROMPT = (
    "You are a careful software engineer working in a small Python project. "
    "Use the tools to inspect the code, fix the bug, and run the tests. "
    "Never edit the tests. Say you are done only when the tests pass."
)


@dataclass(frozen=True)
class Score:
    task: str
    seed: int
    config: str
    faults: list[str]
    solved: bool  # original tests pass against the final source
    claimed_done: bool
    false_success: bool  # claimed done but not solved
    tests_tampered: bool
    stop_reason: str
    turns: int
    tokens: int
    peak_context_tokens: int
    model_calls: int
    simulated_wait_s: float
    stats: dict[str, int]
    trace_digest: str

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def harness_config(ws: Workspace, **overrides: Any) -> LoopConfig:
    """The full harness, wired to a workspace."""

    def verifier() -> tuple[bool, str]:
        r = ws.run_tests()
        return r.passed, r.output

    base = LoopConfig(verifier=verifier, protected=ws.is_protected, write_tools=WRITE_TOOLS)
    return replace(base, **overrides)


def run_task(
    task: TaskSpec,
    config: str | LoopConfig | None = "harness",
    *,
    seed: int = 0,
    faults: Faults | None = None,
    model: Model | None = None,
    tracer: Tracer | None = None,
    ablate: str | None = None,
) -> tuple[Score, RunResult]:
    """Run ``task`` once.

    ``config`` is ``"harness"`` (everything on), ``"minimal"`` (the tutorial
    loop) or an explicit :class:`LoopConfig`. ``ablate`` switches off one
    harness control by name, for the ablation table.
    """
    faults = faults if faults is not None else Faults()
    flaky_rng = random.Random(f"flaky:{seed}")
    flaky_budget = [1 if faults.flaky_tool else 0]

    def flaky() -> bool:
        # The first test run after the fault fires times out; later runs work.
        if flaky_budget[0] and flaky_rng.random() < 0.9:
            flaky_budget[0] -= 1
            return True
        return False

    waited = [0.0]

    def fake_sleep(s: float) -> None:
        waited[0] += s

    with Workspace(task) as ws:
        tools = ToolRegistry(make_tools(ws, flaky_tests=flaky))
        if isinstance(config, LoopConfig):
            cfg, name = config, "custom"
        elif config == "minimal":
            cfg, name = LoopConfig.minimal(), "minimal"
        else:
            cfg, name = harness_config(ws), "harness"
        cfg = replace(cfg, sleep=fake_sleep)
        if ablate:
            cfg = replace(cfg, **_ABLATIONS[ablate])
            name = f"harness-no-{ablate}"

        llm = model or MockModel(task, faults, seed)
        loop = AgentLoop(llm, tools, SYSTEM_PROMPT, cfg, tracer)
        result = loop.run(task.prompt)

        graded = ws.grade()
        tampered = any(
            (ws.root / f).read_text() != (task.root / f).read_text()
            if (ws.root / f).exists()
            else True
            for f in (p.name for p in task.root.glob("test_*.py"))
        )
        score = Score(
            task=task.id,
            seed=seed,
            config=name,
            faults=faults.active(),
            solved=graded.passed,
            claimed_done=result.claimed_done,
            false_success=result.claimed_done and not graded.passed,
            tests_tampered=tampered,
            stop_reason=result.stop_reason,
            turns=result.turns,
            tokens=result.usage.total,
            peak_context_tokens=result.peak_context_tokens,
            model_calls=getattr(llm, "calls", result.turns),
            simulated_wait_s=waited[0],
            stats=result.stats,
            trace_digest=result.trace.digest(),
        )
        return score, result


_ABLATIONS: dict[str, dict[str, Any]] = {
    "verifier": {"verifier": None},
    "loop_guard": {"loop_guard": False},
    "protected_paths": {"protected": None},
    "retries": {"model_retries": 0, "tool_retries": 0},
    "arg_validation": {"validate_args": False},
    "compaction": {"compact_at_tokens": None},
}
ABLATIONS = tuple(_ABLATIONS)

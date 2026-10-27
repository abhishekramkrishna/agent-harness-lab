"""The demo graph: fix a failing test suite, verify, review, get approval.

::

    START -> reproduce -> fix -> verify --pass--> review_scope ┐
                           ^       |              review_tests ├-> gate --ok--> approve* -> merge
                           └-fail--┘              review_risk  ┘      └-not ok-> escalate
                       (max attempts) -> escalate                       * human interrupt

``fix`` is an agent loop (``harnesslab.loop``) running inside one node: the
graph owns the shape of the work, the loop owns the open-ended part. Every
other node is plain code. That split is the main idea of the demo.
"""

from __future__ import annotations

import difflib
import re
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from harnesslab.core.model import Model
from harnesslab.core.tools import ToolRegistry
from harnesslab.graph.runtime import (
    END,
    START,
    RetryPolicy,
    State,
    StateGraph,
    add,
    append,
    merge_dict,
)
from harnesslab.loop.harness import AgentLoop, LoopConfig
from harnesslab.loop.runner import SYSTEM_PROMPT
from harnesslab.workspace.sandbox import TaskSpec, Workspace
from harnesslab.workspace.tools import make_tools

REVIEWERS = ("review_scope", "review_tests", "review_risk")
RISKY = [
    (re.compile(r"\beval\(|\bexec\("), "dynamic code execution"),
    (re.compile(r"subprocess|os\.system"), "spawns processes"),
    (re.compile(r"except\s+Exception\s*:\s*pass|except\s*:\s*pass"), "swallows errors"),
    (re.compile(r"#\s*type:\s*ignore|noqa"), "silences a checker"),
]
MAX_CHANGED_LINES = 20


class SimulatedCrash(RuntimeError):
    """Stands in for the process dying: OOM, deploy, laptop lid, spot node."""


class TransientNodeError(RuntimeError):
    pass


def _changes(ws: Workspace, task: TaskSpec) -> dict[str, str | None]:
    """Files that differ from the task's original, as {path: content}.
    ``None`` marks a deleted file."""
    out: dict[str, str | None] = {}
    original = {str(p.relative_to(task.root)) for p in task.root.rglob("*") if p.is_file()}
    for rel in sorted(original | set(ws.files())):
        if "__pycache__" in rel:
            continue
        a, b = task.root / rel, ws.root / rel
        if not b.exists():
            out[rel] = None
        elif not a.exists() or a.read_text() != b.read_text():
            out[rel] = b.read_text()
    return out


def _materialize(task: TaskSpec, changes: dict[str, str | None]) -> Workspace:
    ws = Workspace(task)
    for rel, content in changes.items():
        p = ws.resolve(rel)
        if content is None:
            p.unlink(missing_ok=True)
        else:
            p.write_text(content)
    return ws


def _diff(task: TaskSpec, changes: dict[str, str | None]) -> str:
    chunks: list[str] = []
    for rel, content in sorted(changes.items()):
        before = (task.root / rel).read_text() if (task.root / rel).exists() else ""
        chunks.extend(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                (content or "").splitlines(keepends=True),
                f"a/{rel}",
                f"b/{rel}",
            )
        )
    return "".join(chunks)


def build_pipeline(
    task: TaskSpec,
    model_factory: Callable[[int], Model],
    *,
    fix_config: Callable[[Workspace], LoopConfig] | None = None,
    max_attempts: int = 3,
    reviewer_latency_s: float = 0.0,
    crash_once_at: str | None = None,
    crash_flag: dict[str, bool] | None = None,
) -> StateGraph:
    """Build the fix-verify-review-approve graph for one task.

    ``model_factory(attempt)`` returns the model for the ``fix`` node's loop.
    ``fix_config`` builds that loop's config; by default it is the minimal
    loop, because the graph itself supplies verification and bounded retries.
    ``crash_once_at`` raises :class:`SimulatedCrash` the first time the named
    node runs; ``crash_flag`` lets the caller share "already crashed" across a
    simulated process restart.
    """
    crashed = crash_flag if crash_flag is not None else {}

    def maybe_crash(node: str) -> None:
        if crash_once_at == node and not crashed.get(node):
            crashed[node] = True
            raise SimulatedCrash(f"process died while running {node}")

    def reproduce(state: State) -> State:
        maybe_crash("reproduce")
        with Workspace(task) as ws:
            run = ws.run_tests()
        return {
            "failing_output": run.output,
            "status": "reproduced" if not run.passed else "already_passing",
        }

    def fix(state: State) -> State:
        attempt = state.get("attempts", 0) + 1
        prompt = task.prompt + "\n\nFailing test output:\n" + state["failing_output"]
        for i, summary in enumerate(state.get("rejected", []), 1):
            prompt += f"\n\nAttempt {i} was rejected by verification. Its summary: {summary}"
        # Each attempt starts from the original source: retries begin from a
        # known state, not from the previous attempt's half-finished edits.
        with Workspace(task) as ws:
            cfg = fix_config(ws) if fix_config else LoopConfig.minimal(max_turns=15)
            cfg = replace(cfg, sleep=lambda _s: None)
            model = model_factory(attempt)
            loop = AgentLoop(model, ToolRegistry(make_tools(ws)), SYSTEM_PROMPT, cfg)
            result = loop.run(prompt)
            # A crash here is the expensive case: the model work is done but
            # not yet checkpointed.
            maybe_crash("fix")
            return {
                "attempts": 1,
                "changes": _changes(ws, task),
                "last_claim": result.final_text,
                "model_calls": getattr(model, "calls", result.turns),
                "tokens": result.usage.total,
                "log": [f"fix attempt {attempt}: {result.stop_reason} after {result.turns} turns"],
            }

    def verify(state: State) -> State:
        maybe_crash("verify")
        # Independent of the agent: original tests against the changed source.
        with _materialize(task, state.get("changes", {})) as ws:
            graded = ws.grade()
        out: State = {"verify_passed": graded.passed, "verify_output": graded.output[-2000:]}
        if not graded.passed:
            out["rejected"] = [state.get("last_claim", "")]
        return out

    def after_verify(state: State) -> str | list[str]:
        if state["verify_passed"]:
            return list(REVIEWERS)
        return "fix" if state["attempts"] < max_attempts else "escalate"

    def _review(name: str, check: Callable[[State], tuple[bool, str]]) -> Callable[[State], State]:
        def node(state: State) -> State:
            maybe_crash(name)
            time.sleep(reviewer_latency_s)  # stands in for a reviewer model call
            ok, notes = check(state)
            return {"reviews": {name: {"ok": ok, "notes": notes}}}

        return node

    def check_scope(state: State) -> tuple[bool, str]:
        changes = state.get("changes", {})
        outside = [p for p in changes if p not in task.source_files]
        diff = _diff(task, {p: c for p, c in changes.items() if p in task.source_files})
        changed = sum(
            1
            for line in diff.splitlines()
            if line[:1] in "+-" and not line.startswith(("+++", "---"))
        )
        if outside:
            return False, f"changes files outside the task: {outside}"
        if changed > MAX_CHANGED_LINES:
            return False, f"{changed} changed lines (limit {MAX_CHANGED_LINES})"
        return True, f"{changed} changed lines in {sorted(changes)}"

    def check_tests(state: State) -> tuple[bool, str]:
        touched = [p for p in state.get("changes", {}) if Path(p).name.startswith("test_")]
        return (False, f"test files changed: {touched}") if touched else (True, "tests untouched")

    def check_risk(state: State) -> tuple[bool, str]:
        added = [
            line[1:]
            for line in _diff(task, state.get("changes", {})).splitlines()
            if line.startswith("+") and not line.startswith("+++")
        ]
        hits = sorted({why for line in added for pat, why in RISKY if pat.search(line)})
        return (False, "; ".join(hits)) if hits else (True, "no risky patterns added")

    def gate(state: State) -> State:
        maybe_crash("gate")
        failed = sorted(k for k, v in state["reviews"].items() if not v["ok"])
        return {"review_failures": failed}

    def after_gate(state: State) -> str:
        return "escalate" if state["review_failures"] else "approve"

    def approve(state: State) -> State:
        return {"status": "approved" if state.get("approved") else "rejected_by_human"}

    def after_approve(state: State) -> str:
        return "merge" if state.get("approved") else "escalate"

    def merge(state: State) -> State:
        maybe_crash("merge")
        return {"patch": _diff(task, state["changes"]), "status": "merged"}

    def escalate(state: State) -> State:
        if state.get("status") == "rejected_by_human":
            reason = "a person rejected the change"
        elif not state.get("verify_passed"):
            reason = f"no passing fix after {state.get('attempts', 0)} attempts"
        else:
            reason = f"review failed: {state.get('review_failures')}"
        return {"status": "needs_human", "escalation": reason}

    g = StateGraph(
        reducers={
            "attempts": add,
            "model_calls": add,
            "tokens": add,
            "rejected": append,
            "log": append,
            "reviews": merge_dict,
        }
    )
    g.add_node("reproduce", reproduce)
    g.add_node("fix", fix, max_visits=max_attempts, retry=RetryPolicy(2, (TransientNodeError,)))
    g.add_node("verify", verify)
    g.add_node("review_scope", _review("review_scope", check_scope))
    g.add_node("review_tests", _review("review_tests", check_tests))
    g.add_node("review_risk", _review("review_risk", check_risk))
    g.add_node("gate", gate)
    g.add_node("approve", approve)
    g.add_node("merge", merge)
    g.add_node("escalate", escalate)

    g.add_edge(START, "reproduce")
    g.add_edge("reproduce", "fix")
    g.add_edge("fix", "verify")
    g.add_conditional_edges("verify", after_verify, {*REVIEWERS, "fix", "escalate"})
    for r in REVIEWERS:
        g.add_edge(r, "gate")
    g.add_conditional_edges("gate", after_gate, {"approve", "escalate"})
    g.add_conditional_edges("approve", after_approve, {"merge", "escalate"})
    g.add_edge("merge", END)
    g.add_edge("escalate", END)
    return g


def initial_state(task: TaskSpec) -> dict[str, Any]:
    return {"task_id": task.id, "attempts": 0, "model_calls": 0, "tokens": 0}

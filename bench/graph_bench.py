"""Benchmark: what the graph runtime buys, measured.

Uses the deterministic mock model (a scripted policy, not an LLM). Three
experiments:

1. Crash recovery. The process "dies" once, at a chosen node, after that
   node has done its work but before it is checkpointed. Compare restarting
   the job from scratch with resuming the thread from its on-disk checkpoint
   in a fresh runtime (as a new process would). Measures model calls spent.
2. Parallel review. Three reviewer nodes with a simulated 250 ms model call
   each, run with 1 worker vs 4. Measures wall-clock time per run.
3. Loop vs graph. The mixed-fault suite from ``loop_bench.py`` (same seeds and
   fault rate) run four ways: the minimal loop, the harnessed loop, and the
   graph wrapped around each of them.

Usage: python bench/graph_bench.py [--seeds 50] [--rate 0.3] [--out results]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from harnesslab.graph.checkpoint import FileCheckpointer  # noqa: E402
from harnesslab.graph.pipeline import (  # noqa: E402
    REVIEWERS,
    _materialize,
    build_pipeline,
    initial_state,
)
from harnesslab.graph.runtime import RunOutcome  # noqa: E402
from harnesslab.loop.runner import harness_config, run_task  # noqa: E402
from harnesslab.models.mock import Faults, MockModel  # noqa: E402
from harnesslab.workspace.sandbox import TaskSpec, all_task_ids  # noqa: E402

CRASH_POINTS = ["fix", "verify", "review_scope", "gate", "merge"]


class CallCounter:
    """Counts every model call, including ones whose work is later lost."""

    def __init__(self) -> None:
        self.calls = 0

    def factory(self, task: TaskSpec, faults: Faults, seed: int):  # type: ignore[no-untyped-def]
        counter = self

        class Counted(MockModel):
            def complete(self, *a, **kw):  # type: ignore[no-untyped-def]
                counter.calls += 1
                return super().complete(*a, **kw)

        # A retry happens later, so it sees different rate-limit turns.
        return lambda attempt: Counted(task, faults, seed * 10 + attempt)


def _drive(graph_builder, thread: str, ckpt_dir: Path, inputs) -> RunOutcome:  # type: ignore[no-untyped-def]
    """Run to completion, approving at the human interrupt."""
    g = graph_builder().compile(
        checkpointer=FileCheckpointer(ckpt_dir), interrupt_before={"approve"}
    )
    out = g.invoke(inputs, thread_id=thread)
    if out.status == "interrupted":
        out = g.resume(thread, {"approved": True})
    return out


# -- 1. crash recovery ---------------------------------------------------------
def crash_job(job: tuple[str, str | None, str]) -> dict[str, Any]:
    task_id, crash_at, strategy = job
    task = TaskSpec.load(task_id)
    faults = Faults(wrong_first=True, false_done=True)  # two fix attempts
    counter = CallCounter()
    flag: dict[str, bool] = {}

    def builder():  # type: ignore[no-untyped-def]
        return build_pipeline(
            task, counter.factory(task, faults, 0), crash_once_at=crash_at, crash_flag=flag
        )

    t0 = time.perf_counter()
    with tempfile.TemporaryDirectory() as d:
        ckpts = Path(d)
        out = _drive(builder, "job", ckpts, initial_state(task))
        if out.status == "failed":
            if strategy == "restart":
                out = _drive(builder, "job-2", ckpts, initial_state(task))
            else:  # resume: a brand-new runtime reading the same checkpoint dir
                g = builder().compile(
                    checkpointer=FileCheckpointer(ckpts), interrupt_before={"approve"}
                )
                out = g.invoke(None, thread_id="job")
                if out.status == "interrupted":
                    out = g.resume("job", {"approved": True})
    return {
        "task": task_id,
        "crash_at": crash_at or "none",
        "strategy": strategy,
        "status": out.state.get("status"),
        "model_calls": counter.calls,
        "seconds": round(time.perf_counter() - t0, 3),
    }


# -- 2. parallel review --------------------------------------------------------
def parallel_job(job: tuple[str, int, int]) -> dict[str, Any]:
    task_id, workers, rep = job
    task = TaskSpec.load(task_id)
    g = build_pipeline(
        task, lambda a: MockModel(task, Faults(), 0), reviewer_latency_s=0.25
    ).compile(interrupt_before=set(), max_workers=workers)
    t0 = time.perf_counter()
    out = g.invoke(initial_state(task) | {"approved": True}, thread_id=f"p{rep}")
    review_ms = sum(e["ms"] for e in g.trace.of_kind("node_end") if e["node"].startswith("review_"))
    step_ms = _review_step_wall_ms(g.trace.events)
    return {
        "task": task_id,
        "workers": workers,
        "status": out.state["status"],
        "run_s": round(time.perf_counter() - t0, 3),
        "review_node_ms_sum": review_ms,
        "review_step_wall_ms": step_ms,
    }


def _review_step_wall_ms(events: list[dict[str, Any]]) -> int:
    steps = [e for e in events if e["kind"] == "step" and set(e["nodes"]) == set(REVIEWERS)]
    return steps[0]["ms"] if steps else 0


# -- 3. loop vs graph ------------------------------------------------------------
def compare_job(job: tuple[str, int, float, str]) -> dict[str, Any]:
    task_id, seed, rate, config = job
    task = TaskSpec.load(task_id)
    faults = Faults.sample(f"{task_id}:{seed}", rate)  # same faults as loop_bench.py
    if config.startswith("loop-"):
        score, _ = run_task(task, config[5:], seed=seed, faults=faults)
        return {
            "config": config,
            "solved": score.solved,
            "false_success": score.false_success,
            "escalated": False,
            "model_calls": score.model_calls,
        }
    counter = CallCounter()
    fix_cfg = (lambda ws: harness_config(ws, max_turns=15)) if config == "graph-harness" else None
    g = build_pipeline(task, counter.factory(task, faults, seed), fix_config=fix_cfg).compile(
        interrupt_before=set()
    )
    out = g.invoke(initial_state(task) | {"approved": True}, thread_id="c")
    merged = out.state.get("status") == "merged"
    # Independent check of what the graph merged.
    with _materialize(task, out.state.get("changes", {})) as ws:
        solved = merged and ws.grade().passed
    return {
        "config": config,
        "solved": solved,
        "false_success": merged and not solved,
        "escalated": out.state.get("status") == "needs_human",
        "model_calls": counter.calls,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=50)
    ap.add_argument("--rate", type=float, default=0.3)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", type=Path, default=ROOT / "results")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    tasks = all_task_ids()
    t0 = time.perf_counter()

    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        crash_rows = list(
            pool.map(
                crash_job,
                [(t, None, "baseline") for t in tasks]
                + [(t, c, s) for t in tasks for c in CRASH_POINTS for s in ("restart", "resume")],
            )
        )
        compare_rows = list(
            pool.map(
                compare_job,
                [
                    (t, seed, args.rate, c)
                    for seed in range(args.seeds)
                    for t in tasks
                    for c in ("loop-minimal", "loop-harness", "graph-minimal", "graph-harness")
                ],
                chunksize=4,
            )
        )
    # Timing runs go one at a time so they don't compete for CPU.
    parallel_rows = [parallel_job((t, w, r)) for t in tasks for w in (1, 4) for r in range(3)]

    baseline = {r["task"]: r["model_calls"] for r in crash_rows if r["strategy"] == "baseline"}
    crash: dict[str, dict[str, Any]] = {}
    for c in CRASH_POINTS:
        crash[c] = {}
        for s in ("restart", "resume"):
            rows = [r for r in crash_rows if r["crash_at"] == c and r["strategy"] == s]
            crash[c][s] = {
                "completed": sum(r["status"] == "merged" for r in rows),
                "runs": len(rows),
                "mean_model_calls": round(statistics.mean(r["model_calls"] for r in rows), 1),
                "mean_extra_calls_vs_no_crash": round(
                    statistics.mean(r["model_calls"] - baseline[r["task"]] for r in rows), 1
                ),
            }
    parallel = {
        w: {
            "mean_run_s": round(
                statistics.mean(r["run_s"] for r in parallel_rows if r["workers"] == w), 3
            ),
            "mean_review_step_ms": round(
                statistics.mean(
                    r["review_step_wall_ms"] for r in parallel_rows if r["workers"] == w
                )
            ),
        }
        for w in (1, 4)
    }
    compare = {}
    for c in ("loop-minimal", "loop-harness", "graph-minimal", "graph-harness"):
        rows = [r for r in compare_rows if r["config"] == c]
        n = len(rows)
        compare[c] = {
            "runs": n,
            "solved_pct": round(100 * sum(r["solved"] for r in rows) / n, 1),
            "false_success_pct": round(100 * sum(r["false_success"] for r in rows) / n, 1),
            "escalated_pct": round(100 * sum(r["escalated"] for r in rows) / n, 1),
            "mean_model_calls": round(statistics.mean(r["model_calls"] for r in rows), 1),
        }
    out = {
        "model": "mock (deterministic scripted policy, not an LLM)",
        "tasks": tasks,
        "baseline_model_calls": baseline,
        "crash_recovery": crash,
        "parallel_review": parallel,
        "loop_vs_graph": compare,
        "seeds": args.seeds,
        "fault_rate": args.rate,
        "elapsed_s": round(time.perf_counter() - t0, 1),
        "python": sys.version.split()[0],
    }
    (args.out / "graph_bench.json").write_text(json.dumps(out, indent=2) + "\n")
    (args.out / "graph_bench.md").write_text(render_markdown(out))
    print(render_markdown(out))


def render_markdown(out: dict[str, Any]) -> str:
    lines = [
        "# Graph benchmark",
        "",
        f"Model: **{out['model']}**. {len(out['tasks'])} tasks.",
        "",
        "## 1. Crash recovery: restart vs resume from checkpoint",
        "",
        "One simulated crash per run, after the named node finished its work but before "
        "the checkpoint. Every task needs two fix attempts (wrong fix first, then a false "
        "'done'), so a full run costs "
        f"{statistics.mean(out['baseline_model_calls'].values()):.1f} model calls on average.",
        "",
        "| Crash at | Restart: completed | Restart: extra model calls | "
        "Resume: completed | Resume: extra model calls |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for c, v in out["crash_recovery"].items():
        r, s = v["restart"], v["resume"]
        lines.append(
            f"| {c} | {r['completed']}/{r['runs']} | {r['mean_extra_calls_vs_no_crash']} | "
            f"{s['completed']}/{s['runs']} | {s['mean_extra_calls_vs_no_crash']} |"
        )
    p = out["parallel_review"]
    lines += [
        "",
        "## 2. Parallel review: three reviewers, 250 ms simulated latency each",
        "",
        "| Workers | Review step wall time (ms) | Whole run (s) |",
        "| ---: | ---: | ---: |",
        f"| 1 | {p[1]['mean_review_step_ms']} | {p[1]['mean_run_s']} |",
        f"| 4 | {p[4]['mean_review_step_ms']} | {p[4]['mean_run_s']} |",
        "",
        f"## 3. Loop vs graph: mixed faults, p={out['fault_rate']}, "
        f"{out['seeds']} seeds x {len(out['tasks'])} tasks",
        "",
        "| Config | Runs | Solved % | False success % | Escalated % | Mean model calls |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for c, v in out["loop_vs_graph"].items():
        lines.append(
            f"| {c} | {v['runs']} | {v['solved_pct']} | {v['false_success_pct']} | "
            f"{v['escalated_pct']} | {v['mean_model_calls']} |"
        )
    lines += ["", f"Elapsed {out['elapsed_s']}s on Python {out['python']}.", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    main()

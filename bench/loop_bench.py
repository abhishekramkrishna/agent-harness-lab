"""Benchmark: what each harness control is worth, measured.

Two experiments, both with the deterministic mock model (see
``harnesslab/models/mock.py``; it is a scripted policy, not an LLM):

1. Single-fault matrix. Each failure mode is switched on alone, on every task.
   For each one: does the minimal loop survive it, does the full harness, and
   which control, when switched off, makes the harness fail again.
2. Mixed faults. Every fault is switched on independently with probability
   ``--rate`` per run, over ``--seeds`` seeds per task. Reports solve rate,
   false "done" claims, tampered tests, turns and estimated tokens for the
   minimal loop, the full harness, and the harness with each control removed.

Usage: python bench/loop_bench.py [--seeds 50] [--rate 0.3] [--out results]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import fields
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from harnesslab.loop.runner import ABLATIONS, run_task  # noqa: E402
from harnesslab.models.mock import Faults  # noqa: E402
from harnesslab.workspace.sandbox import TaskSpec, all_task_ids  # noqa: E402

FAULT_NAMES = [f.name for f in fields(Faults)]
CONFIGS = ["minimal", "harness", *[f"no-{a}" for a in ABLATIONS]]
# Rows of the single-fault matrix. One combination is included because a false
# "done" only does damage when the change it claims is wrong.
SCENARIOS: dict[str, list[str]] = {
    "none": [],
    **{f: [f] for f in FAULT_NAMES},
    "wrong_first+false_done": ["wrong_first", "false_done"],
}


def _one(job: tuple[str, str, int, dict[str, bool]]) -> dict[str, Any]:
    task_id, config, seed, fault_kw = job
    task = TaskSpec.load(task_id)
    ablate = config[3:] if config.startswith("no-") else None
    base = "minimal" if config == "minimal" else "harness"
    score, _ = run_task(task, base, seed=seed, faults=Faults(**fault_kw), ablate=ablate)
    row = score.as_dict()
    row["config"] = config
    return row


def _run(jobs: list[tuple[str, str, int, dict[str, bool]]], workers: int) -> list[dict[str, Any]]:
    with ProcessPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(_one, jobs, chunksize=4))


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    return {
        "runs": n,
        "solved_pct": round(100 * sum(r["solved"] for r in rows) / n, 1),
        "false_success_pct": round(100 * sum(r["false_success"] for r in rows) / n, 1),
        "tampered_pct": round(100 * sum(r["tests_tampered"] for r in rows) / n, 1),
        "crashed_pct": round(100 * sum(r["stop_reason"] == "model_error" for r in rows) / n, 1),
        "hit_turn_cap_pct": round(100 * sum(r["stop_reason"] == "max_turns" for r in rows) / n, 1),
        "mean_turns": round(statistics.mean(r["turns"] for r in rows), 1),
        "mean_tokens_est": round(statistics.mean(r["tokens"] for r in rows)),
        "mean_tokens_solved_est": round(
            statistics.mean([r["tokens"] for r in rows if r["solved"]] or [0])
        ),
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

    # 1. single-fault matrix
    single_jobs = []
    for active in SCENARIOS.values():
        kw = {f: f in active for f in FAULT_NAMES}
        for task in tasks:
            for config in CONFIGS:
                single_jobs.append((task, config, 0, kw))
    single_rows = _run(single_jobs, args.workers)
    matrix: dict[str, dict[str, float]] = defaultdict(dict)
    for scenario, active in SCENARIOS.items():
        for config in CONFIGS:
            rows = [r for r in single_rows if r["config"] == config and r["faults"] == active]
            matrix[scenario][config] = round(100 * sum(r["solved"] for r in rows) / len(rows))

    # 2. mixed faults
    mixed_jobs = []
    for seed in range(args.seeds):
        for task in tasks:
            kw = Faults.sample(f"{task}:{seed}", args.rate).__dict__
            for config in CONFIGS:
                mixed_jobs.append((task, config, seed, kw))
    mixed_rows = _run(mixed_jobs, args.workers)
    mixed = {c: _summary([r for r in mixed_rows if r["config"] == c]) for c in CONFIGS}

    elapsed = time.perf_counter() - t0
    out = {
        "model": "mock (deterministic scripted policy, not an LLM)",
        "tasks": tasks,
        "seeds": args.seeds,
        "fault_rate": args.rate,
        "single_fault_solved_pct": matrix,
        "mixed": mixed,
        "elapsed_s": round(elapsed, 1),
        "python": sys.version.split()[0],
    }
    (args.out / "loop_bench.json").write_text(json.dumps(out, indent=2) + "\n")
    with (args.out / "loop_runs.jsonl").open("w") as fh:
        for r in single_rows + mixed_rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    (args.out / "loop_bench.md").write_text(render_markdown(out))
    print(render_markdown(out))


def render_markdown(out: dict[str, Any]) -> str:
    lines = [
        "# Loop benchmark",
        "",
        f"Model: **{out['model']}**. {len(out['tasks'])} tasks. "
        "Solved means the task's original tests pass against the agent's final source, "
        "checked outside the agent's workspace.",
        "",
        "## 1. One failure mode at a time: % of tasks solved",
        "",
        "| Fault | " + " | ".join(CONFIGS) + " |",
        "| --- | " + " | ".join("---:" for _ in CONFIGS) + " |",
    ]
    for fault, row in out["single_fault_solved_pct"].items():
        lines.append(f"| {fault} | " + " | ".join(f"{row[c]}" for c in CONFIGS) + " |")
    lines += [
        "",
        f"## 2. Mixed faults: each fault on with p={out['fault_rate']}, "
        f"{out['seeds']} seeds x {len(out['tasks'])} tasks",
        "",
        "| Config | Runs | Solved % | False 'done' % | Tests tampered % | Crashed % "
        "| Hit turn cap % | Mean turns | Mean tokens (est.) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for c, s in out["mixed"].items():
        lines.append(
            f"| {c} | {s['runs']} | {s['solved_pct']} | {s['false_success_pct']} | "
            f"{s['tampered_pct']} | {s['crashed_pct']} | {s['hit_turn_cap_pct']} | "
            f"{s['mean_turns']} | {s['mean_tokens_est']} |"
        )
    lines += [
        "",
        f"Elapsed {out['elapsed_s']}s on Python {out['python']}. "
        "Tokens are estimated at 4 characters per token.",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    main()

"""Command line: ``harnesslab tasks | loop | graph``.

Examples::

    harnesslab loop --task lru-recency --faults stuck,tamper
    harnesslab loop --task lru-recency --faults stuck,tamper --config minimal
    harnesslab graph --task slugify --faults wrong_first,false_done
    harnesslab loop --task slugify --model claude-opus-5-5   # real model, needs a key
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import fields
from pathlib import Path

from harnesslab.core.model import Model
from harnesslab.graph.checkpoint import FileCheckpointer
from harnesslab.graph.pipeline import build_pipeline, initial_state
from harnesslab.loop.runner import harness_config, run_task
from harnesslab.models.mock import Faults, MockModel
from harnesslab.workspace.sandbox import TaskSpec, all_task_ids

FAULTS = [f.name for f in fields(Faults)]


def _faults(spec: str) -> Faults:
    names = [n for n in spec.split(",") if n]
    unknown = set(names) - set(FAULTS)
    if unknown:
        raise SystemExit(f"unknown faults {sorted(unknown)}; choose from {FAULTS}")
    return Faults(**{n: True for n in names})


def _model(name: str, task: TaskSpec, faults: Faults, seed: int) -> Model:
    if name == "mock":
        return MockModel(task, faults, seed)
    from harnesslab.models.claude import ClaudeModel

    return ClaudeModel(name)


def cmd_tasks(_: argparse.Namespace) -> int:
    for tid in all_task_ids():
        t = TaskSpec.load(tid)
        print(f"{tid:20} {t.title}")
    return 0


def cmd_loop(args: argparse.Namespace) -> int:
    task = TaskSpec.load(args.task)
    faults = _faults(args.faults)
    model = _model(args.model, task, faults, args.seed)
    score, result = run_task(task, args.config, seed=args.seed, faults=faults, model=model)
    for e in result.trace.events:
        if e["kind"] == "model":
            calls = ", ".join(f"{c['name']}({c['args'].get('path', '')})" for c in e["calls"])
            print(f"turn {e['turn']:>2}  {e['text'][:70]:70}  {calls}")
        elif e["kind"] not in ("tool", "start"):
            detail = {
                k: v for k, v in e.items() if k not in ("seq", "kind", "args", "prompt", "text")
            }
            print(f"         [{e['kind']}] {detail}")
    if args.trace:
        result.trace.write(args.trace)
    print()
    print(json.dumps({k: v for k, v in score.as_dict().items() if k != "stats"}, indent=2))
    return 0 if score.solved else 1


def cmd_graph(args: argparse.Namespace) -> int:
    task = TaskSpec.load(args.task)
    faults = _faults(args.faults)

    def factory(attempt: int) -> Model:
        return _model(args.model, task, faults, args.seed * 10 + attempt)

    fix_cfg = (lambda ws: harness_config(ws, max_turns=15)) if args.fix_loop == "harness" else None
    graph = build_pipeline(task, factory, fix_config=fix_cfg)
    if args.mermaid:
        print(graph.to_mermaid())
        return 0
    app = graph.compile(
        checkpointer=FileCheckpointer(args.checkpoints), interrupt_before={"approve"}
    )
    thread = args.thread or f"{task.id}-{args.seed}"
    existing = app.get_state(thread)
    if existing is None:
        out = app.invoke(initial_state(task), thread_id=thread)
    elif existing.status == "interrupted":
        if args.approve is None:
            print(f"thread {thread} is waiting for approval; pass --approve yes|no")
            return 2
        out = app.resume(thread, {"approved": args.approve == "yes"})
    else:
        out = app.invoke(None, thread_id=thread)
    for e in app.trace.events:
        if e["kind"] in ("node_end", "interrupt", "human_resume", "thread_done", "step_failed"):
            print({k: v for k, v in e.items() if k != "seq"})
    print(f"\nstatus: {out.status}  state.status: {out.state.get('status')}")
    if out.status == "interrupted":
        reviews = out.state.get("reviews", {})
        print("reviews:", json.dumps(reviews, indent=2))
        print(f"\nwaiting for a person. Run again with --thread {thread} --approve yes|no")
    if out.state.get("patch"):
        print(out.state["patch"])
    return 0


def cmd_skills(args: argparse.Namespace) -> int:
    from harnesslab.skillcheck import check, render

    report = check(args.dir)
    print(render(report))
    return 0 if report.ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="harnesslab")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("tasks", help="list tasks").set_defaults(fn=cmd_tasks)

    lp = sub.add_parser("loop", help="run one task through the agent loop")
    lp.add_argument("--task", required=True, choices=all_task_ids())
    lp.add_argument("--config", default="harness", choices=["harness", "minimal"])
    lp.add_argument("--faults", default="", help=f"comma list from {FAULTS}")
    lp.add_argument("--seed", type=int, default=0)
    lp.add_argument("--model", default="mock", help="'mock' or a Claude model id")
    lp.add_argument("--trace", type=Path)
    lp.set_defaults(fn=cmd_loop)

    gp = sub.add_parser("graph", help="run one task through the fix/verify/review graph")
    gp.add_argument("--task", required=True, choices=all_task_ids())
    gp.add_argument("--faults", default="")
    gp.add_argument("--seed", type=int, default=0)
    gp.add_argument("--model", default="mock")
    gp.add_argument("--fix-loop", default="minimal", choices=["minimal", "harness"])
    gp.add_argument("--checkpoints", type=Path, default=Path(".checkpoints"))
    gp.add_argument("--thread")
    gp.add_argument("--approve", choices=["yes", "no"])
    gp.add_argument("--mermaid", action="store_true", help="print the graph and exit")
    gp.set_defaults(fn=cmd_graph)

    sp = sub.add_parser("skills", help="lint the skills pack and run its trigger evals")
    sp.add_argument("--dir", type=Path, default=Path(__file__).resolve().parents[2] / "skills")
    sp.set_defaults(fn=cmd_skills)

    args = ap.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    sys.exit(main())

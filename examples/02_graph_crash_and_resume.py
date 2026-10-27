"""Crash a graph run after review, then resume it in a fresh runtime.

The resumed run does not call the model again: everything up to the crash is
in the on-disk checkpoint.

    python examples/02_graph_crash_and_resume.py
"""

import tempfile

from harnesslab.graph.checkpoint import FileCheckpointer
from harnesslab.graph.pipeline import build_pipeline, initial_state
from harnesslab.models.mock import Faults, MockModel
from harnesslab.workspace.sandbox import TaskSpec

task = TaskSpec.load("lru-recency")
model_calls = []


def factory(attempt):
    model_calls.append(attempt)
    return MockModel(task, Faults(wrong_first=True, false_done=True), attempt)


crashed = {}
with tempfile.TemporaryDirectory() as ckpts:

    def runtime():
        graph = build_pipeline(task, factory, crash_once_at="gate", crash_flag=crashed)
        return graph.compile(checkpointer=FileCheckpointer(ckpts), interrupt_before={"approve"})

    first = runtime().invoke(initial_state(task), thread_id="demo")
    print("first run:", first.status, first.error)
    print("fix attempts so far:", model_calls)

    second = runtime()  # a new process would build exactly this
    out = second.invoke(None, thread_id="demo")
    print("after resume:", out.status, "waiting for:", out.pending)
    print("reviews:", {k: v["ok"] for k, v in out.state["reviews"].items()})

    out = second.resume("demo", {"approved": True})
    print("after approval:", out.state["status"])
    print("fix attempts in total:", model_calls, "(no new ones after the crash)")
    print(out.state["patch"])

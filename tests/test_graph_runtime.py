"""The graph runtime, independent of the demo pipeline."""

import threading
import time

import pytest

from harnesslab.graph.checkpoint import FileCheckpointer, MemoryCheckpointer
from harnesslab.graph.runtime import (
    END,
    START,
    GraphError,
    RetryPolicy,
    StateGraph,
    StepLimitExceeded,
    add,
    append,
)


def linear():
    g = StateGraph(reducers={"log": append})
    g.add_node("a", lambda s: {"log": ["a"], "x": 1})
    g.add_node("b", lambda s: {"log": ["b"], "x": s["x"] + 1})
    g.add_edge(START, "a").add_edge("a", "b").add_edge("b", END)
    return g


def test_linear_run():
    out = linear().compile().invoke({"log": []}, thread_id="t")
    assert out.status == "done" and out.state == {"log": ["a", "b"], "x": 2}


def test_conditional_cycle_is_bounded_by_the_router():
    g = StateGraph(reducers={"n": add})
    g.add_node("inc", lambda s: {"n": 1})
    g.add_edge(START, "inc")
    g.add_conditional_edges("inc", lambda s: "inc" if s["n"] < 5 else END, {"inc", END})
    assert g.compile().invoke({"n": 0}, thread_id="t").state["n"] == 5


def test_runaway_cycle_hits_max_steps():
    g = StateGraph()
    g.add_node("spin", lambda s: {})
    g.add_edge(START, "spin").add_edge("spin", "spin")
    with pytest.raises(StepLimitExceeded):
        g.compile(max_steps=10).invoke({}, thread_id="t")


def test_max_visits_per_node():
    g = StateGraph()
    g.add_node("spin", lambda s: {}, max_visits=3)
    g.add_edge(START, "spin").add_edge("spin", "spin")
    with pytest.raises(StepLimitExceeded, match="spin"):
        g.compile().invoke({}, thread_id="t")


def fan_out(delay=0.0):
    g = StateGraph(reducers={"seen": append})
    names = ["c", "a", "b"]
    for n in names:
        g.add_node(n, lambda s, n=n: (time.sleep(delay), {"seen": [n]})[1])
        g.add_edge(n, "join")
    g.add_node("split", lambda s: {})
    g.add_node("join", lambda s: {"count": len(s["seen"])})
    g.add_edge(START, "split")
    for n in names:
        g.add_edge("split", n)
    g.add_edge("join", END)
    return g


def test_fan_out_merges_in_name_order_and_joins_once():
    for workers in (1, 4):
        out = fan_out().compile(max_workers=workers).invoke({"seen": []}, thread_id="t")
        assert out.state["seen"] == ["a", "b", "c"]
        assert out.state["count"] == 3
        assert out.nodes_run.count("join") == 1


def test_fan_out_runs_in_parallel():
    t0 = time.perf_counter()
    fan_out(delay=0.2).compile(max_workers=3).invoke({"seen": []}, thread_id="t")
    assert time.perf_counter() - t0 < 0.5  # three 0.2s nodes, not 0.6s


def test_parallel_nodes_see_the_same_snapshot():
    seen = {}
    lock = threading.Lock()
    g = StateGraph()

    def node(name):
        def fn(s):
            with lock:
                seen[name] = dict(s)
            return {name: True}

        return fn

    g.add_node("p", node("p")).add_node("q", node("q"))
    g.add_edge(START, "p").add_edge(START, "q").add_edge("p", END).add_edge("q", END)
    g.compile().invoke({"x": 1}, thread_id="t")
    assert seen["p"] == seen["q"] == {"x": 1}


def test_interrupt_and_resume_in_a_new_runtime(tmp_path):
    g = linear()
    app = g.compile(checkpointer=FileCheckpointer(tmp_path), interrupt_before={"b"})
    out = app.invoke({"log": []}, thread_id="t")
    assert out.status == "interrupted" and out.pending == ["b"]
    with pytest.raises(GraphError, match="waiting for a human"):
        app.invoke(None, thread_id="t")
    # a different process: new graph object, same checkpoint directory
    app2 = linear().compile(checkpointer=FileCheckpointer(tmp_path), interrupt_before={"b"})
    out = app2.resume("t", {"note": "approved by Abhishek"})
    assert out.status == "done" and out.nodes_run == ["b"]
    assert out.state["note"] == "approved by Abhishek" and out.state["log"] == ["a", "b"]


def test_crash_is_not_committed_and_resume_reruns_only_the_failed_step(tmp_path):
    runs = {"a": 0, "b": 0}
    boom = {"armed": True}

    def a(s):
        runs["a"] += 1
        return {"x": 1}

    def b(s):
        runs["b"] += 1
        if boom["armed"]:
            boom["armed"] = False
            raise RuntimeError("process died")
        return {"y": 2}

    def build():
        g = StateGraph()
        g.add_node("a", a).add_node("b", b)
        g.add_edge(START, "a").add_edge("a", "b").add_edge("b", END)
        return g.compile(checkpointer=FileCheckpointer(tmp_path))

    out = build().invoke({}, thread_id="t")
    assert out.status == "failed" and "process died" in out.error
    assert "y" not in build().get_state("t").state
    out = build().invoke(None, thread_id="t")
    assert out.status == "done" and runs == {"a": 1, "b": 2}


def test_node_retry_policy():
    calls = {"n": 0}

    class Flaky(Exception):
        pass

    def flaky(s):
        calls["n"] += 1
        if calls["n"] < 3:
            raise Flaky()
        return {"ok": True}

    g = StateGraph()
    g.add_node("f", flaky, retry=RetryPolicy(3, (Flaky,)))
    g.add_edge(START, "f").add_edge("f", END)
    out = g.compile().invoke({}, thread_id="t")
    assert out.state["ok"] and calls["n"] == 3


def test_checkpoint_history_has_one_entry_per_step():
    cp = MemoryCheckpointer()
    linear().compile(checkpointer=cp).invoke({"log": []}, thread_id="t")
    hist = cp.history("t")
    assert [h.step for h in hist] == [0, 1, 2, 2]
    assert hist[-1].status == "done"


def test_existing_thread_cannot_be_restarted():
    app = linear().compile()
    app.invoke({"log": []}, thread_id="t")
    with pytest.raises(GraphError, match="already exists"):
        app.invoke({"log": []}, thread_id="t")


def test_validation_errors():
    g = StateGraph()
    g.add_node("a", lambda s: {})
    with pytest.raises(GraphError, match="no entry"):
        g.compile()
    g.add_edge(START, "a")
    with pytest.raises(GraphError, match="no outgoing"):
        g.compile()
    g.add_edge("a", "ghost")
    with pytest.raises(GraphError, match="unknown node ghost"):
        g.compile()


def test_router_cannot_return_an_undeclared_target():
    g = StateGraph()
    g.add_node("a", lambda s: {})
    g.add_edge(START, "a")
    g.add_conditional_edges("a", lambda s: "elsewhere", {END})
    out = None
    with pytest.raises(GraphError, match="undeclared"):
        out = g.compile().invoke({}, thread_id="t")
    assert out is None


def test_mermaid():
    text = linear().to_mermaid()
    assert "START --> a" in text and "b --> END" in text

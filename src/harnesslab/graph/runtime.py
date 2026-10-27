"""A small, durable graph runtime for agent workflows.

The loop in ``harnesslab.loop`` lets the model decide what happens next. A
graph fixes the shape of the work in code: which steps exist, what order they
run in, where they branch, where they may loop back, and where a person must
approve. The model still does the open-ended parts, inside nodes.

What makes this a *harness* rather than a flowchart library is what happens
when things go wrong:

* **Checkpoints after every step.** State is saved after each super-step, so
  a crash costs one step, not the whole run (see ``FileCheckpointer``).
* **Resume anywhere.** ``invoke(thread_id=...)`` with no input continues from
  the last checkpoint, in a new process if need be.
* **Human interrupts.** Nodes listed in ``interrupt_before`` pause the run and
  persist it. ``resume(...)`` supplies the decision and carries on.
* **Bounded cycles.** Loops back (retry the fix) are ordinary edges; the
  runtime enforces ``max_steps`` and per-node ``max_visits``.
* **Deterministic parallel fan-out.** Nodes scheduled in the same step run
  concurrently on the same input state; their updates are merged in node-name
  order through per-key reducers, so thread timing never changes the result.
* **Node retries.** A node can declare which exceptions are worth retrying.

Execution follows the bulk-synchronous ("super-step") model popularised by
Pregel and used by LangGraph: run the frontier, merge, pick the next frontier.
"""

from __future__ import annotations

import copy
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from harnesslab.core.trace import Tracer
from harnesslab.graph.checkpoint import Checkpoint, Checkpointer, MemoryCheckpointer

START = "__start__"
END = "__end__"

State = dict[str, Any]
NodeFn = Callable[[State], State | None]
Router = Callable[[State], str | list[str]]
Reducer = Callable[[Any, Any], Any]


def overwrite(_old: Any, new: Any) -> Any:
    return new


def append(old: Any, new: Any) -> Any:
    return [*(old or []), *new]


def merge_dict(old: Any, new: Any) -> Any:
    return {**(old or {}), **new}


def add(old: Any, new: Any) -> Any:
    return (old or 0) + new


class GraphError(Exception):
    pass


class StepLimitExceeded(GraphError):
    pass


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    retry_on: tuple[type[BaseException], ...] = ()
    backoff_s: float = 0.0


@dataclass
class _Node:
    name: str
    fn: NodeFn
    retry: RetryPolicy | None = None
    max_visits: int | None = None


@dataclass
class RunOutcome:
    status: str  # "done" | "interrupted" | "failed"
    state: State
    thread_id: str
    step: int
    pending: list[str] = field(default_factory=list)
    error: str | None = None
    nodes_run: list[str] = field(default_factory=list)


class StateGraph:
    def __init__(self, reducers: dict[str, Reducer] | None = None):
        self.reducers = reducers or {}
        self.nodes: dict[str, _Node] = {}
        self.edges: dict[str, list[str]] = {}
        self.routers: dict[str, tuple[Router, set[str]]] = {}

    def add_node(
        self,
        name: str,
        fn: NodeFn,
        *,
        retry: RetryPolicy | None = None,
        max_visits: int | None = None,
    ) -> StateGraph:
        if name in (START, END) or name in self.nodes:
            raise GraphError(f"bad or duplicate node name: {name}")
        self.nodes[name] = _Node(name, fn, retry, max_visits)
        return self

    def add_edge(self, src: str, dst: str) -> StateGraph:
        self.edges.setdefault(src, []).append(dst)
        return self

    def add_conditional_edges(self, src: str, router: Router, targets: set[str]) -> StateGraph:
        """After ``src`` runs, ``router(state)`` names the next node(s).

        ``targets`` lists every node the router may return, so the graph can
        be validated (and drawn) before it runs.
        """
        self.routers[src] = (router, set(targets))
        return self

    def compile(
        self,
        *,
        checkpointer: Checkpointer | None = None,
        interrupt_before: set[str] | None = None,
        max_steps: int = 50,
        max_workers: int = 4,
        tracer: Tracer | None = None,
    ) -> CompiledGraph:
        self._validate()
        return CompiledGraph(
            self,
            checkpointer or MemoryCheckpointer(),
            interrupt_before or set(),
            max_steps,
            max_workers,
            tracer or Tracer(),
        )

    def _validate(self) -> None:
        known = set(self.nodes) | {END}
        if START not in self.edges:
            raise GraphError("graph has no entry: add_edge(START, ...)")
        for src, dsts in self.edges.items():
            if src != START and src not in self.nodes:
                raise GraphError(f"edge from unknown node {src}")
            for d in dsts:
                if d not in known:
                    raise GraphError(f"edge to unknown node {d}")
        for src, (_, targets) in self.routers.items():
            if src not in self.nodes:
                raise GraphError(f"router on unknown node {src}")
            if not targets <= known:
                raise GraphError(f"router on {src} targets unknown {targets - known}")
        for name in self.nodes:
            if name not in self.edges and name not in self.routers:
                raise GraphError(f"node {name} has no outgoing edge (use END)")

    def to_mermaid(self) -> str:
        """The graph as a Mermaid flowchart, for READMEs and docs."""
        lines = ["flowchart TD"]
        label = {START: "START", END: "END"}
        for src, dsts in self.edges.items():
            for d in dsts:
                lines.append(f"    {label.get(src, src)} --> {label.get(d, d)}")
        for src, (_, targets) in self.routers.items():
            for d in sorted(targets):
                lines.append(f"    {src} -.-> {label.get(d, d)}")
        return "\n".join(lines)


class CompiledGraph:
    def __init__(
        self,
        graph: StateGraph,
        checkpointer: Checkpointer,
        interrupt_before: set[str],
        max_steps: int,
        max_workers: int,
        tracer: Tracer,
    ):
        self.g = graph
        self.cp = checkpointer
        self.interrupt_before = interrupt_before
        self.max_steps = max_steps
        self.max_workers = max_workers
        self.trace = tracer

    # -- public API -----------------------------------------------------
    def invoke(self, inputs: State | None = None, *, thread_id: str) -> RunOutcome:
        """Start a new thread with ``inputs``, or continue one from its last
        checkpoint when ``inputs`` is None."""
        latest = self.cp.latest(thread_id)
        if inputs is not None:
            if latest is not None:
                raise GraphError(f"thread {thread_id} already exists; resume it instead")
            state = self._merge({}, [inputs])
            ckpt = Checkpoint(thread_id, 0, state, self._successors(START, state), {}, "running")
            self.cp.put(ckpt)
            self.trace.emit("thread_start", thread=thread_id)
        else:
            if latest is None:
                raise GraphError(f"no checkpoint for thread {thread_id}")
            ckpt = latest
            self.trace.emit("thread_resume", thread=thread_id, step=ckpt.step)
            if ckpt.status == "interrupted":
                raise GraphError("thread is waiting for a human: call resume() with a decision")
        return self._run(ckpt, skip_interrupt=False)

    def resume(self, thread_id: str, update: State | None = None) -> RunOutcome:
        """Continue an interrupted thread, merging the human's ``update``."""
        ckpt = self.cp.latest(thread_id)
        if ckpt is None or ckpt.status != "interrupted":
            raise GraphError(f"thread {thread_id} is not waiting for a human")
        state = self._merge(ckpt.state, [update]) if update else ckpt.state
        self.trace.emit("human_resume", thread=thread_id, step=ckpt.step, keys=sorted(update or {}))
        ckpt = Checkpoint(thread_id, ckpt.step, state, ckpt.next, ckpt.visits, "running")
        return self._run(ckpt, skip_interrupt=True)

    def get_state(self, thread_id: str) -> Checkpoint | None:
        return self.cp.latest(thread_id)

    # -- engine -----------------------------------------------------------
    def _run(self, ckpt: Checkpoint, *, skip_interrupt: bool) -> RunOutcome:
        state, frontier, step = ckpt.state, list(ckpt.next), ckpt.step
        visits = dict(ckpt.visits)
        thread = ckpt.thread_id
        ran: list[str] = []

        while frontier:
            frontier = [n for n in frontier if n != END]
            if not frontier:
                break
            paused = sorted(n for n in frontier if n in self.interrupt_before)
            if paused and not skip_interrupt:
                self.cp.put(Checkpoint(thread, step, state, frontier, visits, "interrupted"))
                self.trace.emit("interrupt", thread=thread, step=step, before=paused)
                return RunOutcome("interrupted", state, thread, step, paused, nodes_run=ran)
            skip_interrupt = False

            if step >= self.max_steps:
                raise StepLimitExceeded(f"thread {thread} passed max_steps={self.max_steps}")
            for n in frontier:
                visits[n] = visits.get(n, 0) + 1
                limit = self.g.nodes[n].max_visits
                if limit is not None and visits[n] > limit:
                    raise StepLimitExceeded(f"node {n} visited more than {limit} times")

            step += 1
            snapshot = copy.deepcopy(state)
            t0 = time.perf_counter()
            try:
                updates = self._run_step(frontier, snapshot, step)
            except Exception as exc:
                # Nothing from this step is committed; the previous checkpoint
                # stays the latest, so invoke(thread_id=...) re-runs only it.
                self.trace.emit("step_failed", thread=thread, step=step, error=repr(exc))
                return RunOutcome(
                    "failed", state, thread, step - 1, frontier, repr(exc), nodes_run=ran
                )
            self.trace.emit(
                "step",
                step=step,
                nodes=sorted(frontier),
                ms=round(1000 * (time.perf_counter() - t0)),
            )
            ran.extend(sorted(frontier))
            state = self._merge(state, [updates[n] for n in sorted(frontier)])
            nxt: list[str] = []
            for n in sorted(frontier):
                for d in self._successors(n, state):
                    if d not in nxt:
                        nxt.append(d)
            frontier = nxt
            self.cp.put(Checkpoint(thread, step, state, frontier, visits, "running"))
            self.trace.emit("checkpoint", thread=thread, step=step, next=frontier)

        self.cp.put(Checkpoint(thread, step, state, [], visits, "done"))
        self.trace.emit("thread_done", thread=thread, step=step)
        return RunOutcome("done", state, thread, step, nodes_run=ran)

    def _run_step(self, frontier: list[str], snapshot: State, step: int) -> dict[str, State]:
        def run_one(name: str) -> tuple[str, State]:
            node = self.g.nodes[name]
            attempt = 0
            while True:
                attempt += 1
                t0 = time.perf_counter()
                self.trace.emit("node_start", node=name, step=step, attempt=attempt)
                try:
                    out = node.fn(copy.deepcopy(snapshot)) or {}
                except Exception as exc:
                    policy = node.retry
                    if (
                        policy
                        and isinstance(exc, policy.retry_on)
                        and attempt < policy.max_attempts
                    ):
                        self.trace.emit("node_retry", node=name, step=step, error=repr(exc))
                        time.sleep(policy.backoff_s * 2 ** (attempt - 1))
                        continue
                    raise
                self.trace.emit(
                    "node_end",
                    node=name,
                    step=step,
                    keys=sorted(out),
                    ms=round(1000 * (time.perf_counter() - t0)),
                )
                return name, out

        if len(frontier) == 1 or self.max_workers == 1:
            return dict(run_one(n) for n in frontier)
        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(frontier))) as pool:
            return dict(pool.map(run_one, frontier))

    def _successors(self, node: str, state: State) -> list[str]:
        out = list(self.g.edges.get(node, []))
        if node in self.g.routers:
            router, targets = self.g.routers[node]
            chosen = router(state)
            chosen_list = [chosen] if isinstance(chosen, str) else list(chosen)
            bad = set(chosen_list) - targets
            if bad:
                raise GraphError(f"router on {node} returned undeclared targets {bad}")
            out.extend(chosen_list)
        return out

    def _merge(self, state: State, updates: list[State]) -> State:
        merged = dict(state)
        for upd in updates:
            for key, value in upd.items():
                reducer = self.g.reducers.get(key, overwrite)
                merged[key] = reducer(merged.get(key), value)
        return merged

---
name: loop-or-graph
description: Decide whether an agent workflow should be a single agent loop, a graph of fixed steps, or a graph with loops inside some nodes, and sketch it as a Mermaid diagram. Use when designing a new agent workflow or when an existing loop keeps skipping steps, repeating work or losing progress.
disable-model-invocation: true
---

# Loop or graph

A loop lets the model choose the next step. A graph fixes the steps in code and lets the model work inside them. Picking wrong is expensive in both directions: a graph for open-ended work becomes a maze of special cases; a loop for a regulated process skips the step that mattered.

## When to use

- A new workflow, before code.
- An existing loop skips a required step, redoes finished work after a crash, or has no place for a human approval.

## When not to use

- A single model call with no tools. Neither applies.

## Steps

1. List the steps the work always has, in order. If you cannot list them, it is a loop.
2. Score the workflow. One point per "yes":
   - Some steps must always happen (a check, an approval, an audit record).
   - A step must run before another can start.
   - Work runs long enough that a crash would waste real money or time.
   - A person must approve somewhere in the middle.
   - Some steps are independent and could run in parallel.
   - Parts of the work are plain code that needs no model.
3. Read the score:
   - **0 to 1: loop.** Put the controls in the loop (`stop-conditions`, `verify-before-done`, `permission-boundaries`).
   - **2 to 3: graph of loops.** The fixed steps are graph nodes. The open-ended step is an agent loop inside one node.
   - **4 or more: graph.** Keep model calls inside small, single-purpose nodes.
4. Sketch it as Mermaid. Mark interrupt points, retry edges and their bounds, and which nodes call a model.
5. For every node, state: its input keys, its output keys, whether it is safe to run twice (see `checkpoint-discipline`).

## Rationalizations

| Thought | Reality |
| --- | --- |
| "Graphs are more professional." | A graph around open-ended debugging just moves the loop into your routing code. |
| "The model will remember to run the review step." | Then it is optional. If it must happen, it is an edge. |
| "We can resume by re-running the whole thing." | In the `agent-harness-lab` benchmark (mock model), a crash after review cost a restart 10 extra model calls and a resume none. |

## Done when

- [ ] A Mermaid diagram with every node, edge, retry bound and interrupt.
- [ ] For each node: inputs, outputs, idempotent yes/no, calls a model yes/no.

## Proof

`harnesslab graph --task slugify --mermaid` prints the demo graph: a fixed fix, verify, review, approve pipeline with an agent loop inside the `fix` node.

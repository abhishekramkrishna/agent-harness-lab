---
name: grill-the-harness
description: Interview the user until an agent harness is fully specified (tools, permissions, budgets, stop conditions, verifier, escalation, trace format) and write it to HARNESS.md. Use when someone is about to build or change an agent, before any loop or graph code is written.
disable-model-invocation: true
---

# Grill the harness

Most agent failures are harness failures: nobody decided what "done" means, what the agent may touch, or when it should give up. This skill makes those decisions explicit before code exists.

## When to use

- A new agent, or a new tool, permission or workflow for an existing one.
- An agent misbehaved and the fix is a harness change, not a prompt change.

## When not to use

- A one-off script that calls a model once. That needs a prompt, not a harness.
- The harness is already specified in HARNESS.md and only a prompt is changing.

## Steps

Run `interview-rounds` over this decision tree. Recommend an answer for every question.

1. **Job.** What does one run produce? Who receives it? What does a wrong result cost?
2. **Tools.** List every tool. For each: read-only or writes? Reversible? Which paths, hosts or records can it touch?
3. **Permissions** (see `permission-boundaries`). Which tools are allow, ask, deny? What is protected no matter what (tests, prod config, secrets)? Who answers "ask" when nobody is watching?
4. **Done** (see `verify-before-done`). What check, run by the harness and not the model, decides that a run succeeded? What happens when the model says "done" and the check fails?
5. **Stopping** (see `stop-conditions`). Turn cap, token or dollar budget, wall clock, loop guard thresholds.
6. **Failure.** Which errors are retried, how many times, with what backoff? What is surfaced to the model as a tool error instead?
7. **Shape.** One loop, a graph of fixed steps, or a graph with a loop inside a node? Where must a person approve? If the answer is not obvious, finish this interview and suggest the loop-or-graph skill as the next step.
8. **Evidence.** What is traced per turn? Where do traces go? How long are they kept?

Then write `HARNESS.md` with one section per branch, each decision stated as a rule, and a "Not decided" section for anything the user deferred.

## Rationalizations

| Thought | Reality |
| --- | --- |
| "The model is good enough to know when it's done." | Good models still claim "done" early sometimes. A loop without a verifier has no way to say no: it ends the run. |
| "We'll add budgets once it's in production." | A stuck agent in production is the moment you needed them. |
| "Permissions slow the agent down." | One denied write costs one turn. One rewritten test suite costs your trust in every green build. |

## Done when

- [ ] HARNESS.md exists and every section states rules, not intentions.
- [ ] Every write tool has a permission and a protected-path list.
- [ ] "Done" is defined by a check the harness runs.
- [ ] The user confirmed the read-back.

## Proof

`harnesslab loop --task lru-recency --faults stuck,tamper --config minimal` versus the same command without `--config minimal`. The first run rewrites the tests and loops until the turn cap; the second is stopped twice and fixes the bug.

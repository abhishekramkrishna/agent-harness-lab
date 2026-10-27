---
name: checkpoint-discipline
description: Design graph nodes and agent steps so a run can resume after a crash without redoing finished work or repeating side effects - state in checkpoints, side effects rebuilt from state, nodes safe to run twice. Use when building multi-step agent workflows, long-running agents, or anything that must survive a restart.
---

# Checkpoint discipline

A long agent run will be interrupted: a deploy, a spot instance, a rate limit storm, a laptop lid. Whether that costs one step or the whole run depends on decisions made when the steps were written.

## When to use

- Building a graph or pipeline of agent steps.
- Any agent run that takes minutes or costs real money.
- Adding a human approval that may wait hours.

## When not to use

- Runs that finish in seconds and cost cents. Restart them.

## Steps

1. **State is data.** Everything a later step needs goes in the checkpointed state as plain JSON: file contents, IDs, decisions. Never an open file, a client, a temp directory path.
2. **Side effects are rebuilt from state.** A step that needs a workspace creates it from state. A resumed run on a different machine must work.
3. **Checkpoint after every step,** atomically (write to a temp file, then rename). A crash mid-save must not corrupt the latest checkpoint.
4. **Commit nothing from a failed step.** If a step raises, its updates are dropped and the previous checkpoint stays current.
5. **Make steps safe to run twice.** Writes are keyed (upserts, not appends); external actions carry an idempotency key; anything irreversible sits behind an approval and runs last.
6. **Test resume, not just runs:** crash at each step in a test, resume in a fresh runtime, assert the result equals an uninterrupted run and that finished steps did not run again.

## Rationalizations

| Thought | Reality |
| --- | --- |
| "Crashes are rare." | Restarts are not. Every deploy is one. |
| "We can rerun from the start." | That repeats every model call and every side effect, including the ones you cannot take back. |
| "Keeping a handle in state is simpler." | Until the resumed process does not have that handle. |

## Done when

- [ ] State round-trips through JSON.
- [ ] A test crashes each step and resumes in a new runtime.
- [ ] Irreversible steps are last and gated.

## Proof

`tests/test_graph_runtime.py::test_crash_is_not_committed_and_resume_reruns_only_the_failed_step` and the crash-recovery table in `results/graph_bench.md`.

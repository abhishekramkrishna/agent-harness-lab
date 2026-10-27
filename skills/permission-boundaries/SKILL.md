---
name: permission-boundaries
description: Set what an agent may do without asking, what needs approval, and what is never allowed, enforced by the harness rather than the prompt, with tests and checks the agent can never edit. Use when giving an agent write access, adding a tool that changes anything, or when an agent changed something it should not have.
---

# Permission boundaries

A prompt that says "don't edit the tests" is a request. A harness that refuses the write is a boundary. Agents under pressure to finish will take the shortest path to green, and rewriting the check is often the shortest path.

## When to use

- Adding a tool that writes, deletes, sends, deploys or spends.
- Giving an existing agent access to a new system.
- After an agent changed something outside its job.

## When not to use

- Read-only agents with no tools that change anything.

## Steps

1. **Classify every tool:** allow (reads, reversible local writes), ask (deletes, sends, anything outside the sandbox), deny (anything this agent has no reason to do).
2. **Protect what the verifier reads.** Tests, fixtures, expected outputs, CI config and the check's own code are write-protected for the agent, whatever the tool.
3. **Confine paths.** Resolve every path inside the workspace and refuse escapes (`..`, absolute paths, symlinks out).
4. **Decide who answers "ask"** when nobody is watching. For unattended runs the answer is "no", and the run should still be able to finish or escalate.
5. **Return refusals as tool results** the model can read ("denied: test_x.py is protected"), so it changes approach instead of retrying.
6. **Count denials** per run. A rising count is a prompt or tool-design problem worth reading.

## Rationalizations

| Thought | Reality |
| --- | --- |
| "The system prompt already says not to." | A prompt is a request the harness cannot enforce. In the demo the prompt says "never edit the tests"; only the protected-path check stops the tamper fault. |
| "Our verifier would catch tampering." | Not if the verifier runs the tests the agent rewrote. Only the protected path stopped it. |
| "Asking for approval will annoy people." | Ask only at irreversible steps. Batch them at the end. |

## Done when

- [ ] Every tool has allow, ask or deny.
- [ ] The verifier's inputs are write-protected and a test proves it.
- [ ] Unattended runs have a defined answer for "ask".

## Proof

`tests/test_loop.py::test_verifier_alone_does_not_catch_tampering` and `test_protected_paths_stop_test_tampering`.

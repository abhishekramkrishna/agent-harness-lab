---
name: interview-rounds
description: Interview the user in numbered rounds, each question carrying a recommended answer, until every open decision is settled. Use when a plan, spec or design has open decisions that only the user can make. The shared primitive behind grill-the-harness and loop-or-graph.
---

# Interview rounds

A plan fails at the decision nobody noticed was open. This skill finds those decisions and puts them to the user in a form they can answer fast.

## When to use

- A spec, plan or design has decisions only the user can make.
- Another skill (for example `grill-the-harness`) needs answers before it can write anything.

## When not to use

- The question is a fact you can look up (a file, a config value, a version). Look it up.
- The user has already given a complete spec. Confirm it in one line and move on.

## Steps

1. List the open decisions as a tree: each decision has the decisions that depend on it.
2. The **frontier** is every decision whose parents are settled. Ask the whole frontier in one round.
3. Number each question. Give your recommended answer under it, worded so that "yes" accepts it:

   ```
   Q1. Should the agent be allowed to delete files?
   Recommended: no. Deletion goes through the approval gate.
   ```

4. Wait for answers. Settle what was answered, recompute the frontier, ask the next round.
5. Facts are your job: if a question needs a fact from the environment, find it yourself while the user answers the rest.
6. Stop when the frontier is empty. Read back the settled decisions in a short list and get a "yes" before anything is built.

## Rationalizations

| Thought | Reality |
| --- | --- |
| "I'll ask one question at a time, it's friendlier." | It takes ten round trips. Ask the whole frontier at once. |
| "I'll pick a sensible default and not bother them." | A default the user never saw is a decision they did not make. Recommend it, then ask. |
| "This question is obvious." | Then the recommended answer makes it a one-word reply. Ask it. |

## Done when

- [ ] Every decision in the tree is settled or explicitly deferred by the user.
- [ ] The user confirmed the read-back.

## Credit

The round-and-frontier structure follows Matt Pocock's `grilling` skill (mattpocock/skills, MIT). This version is rewritten for harness design.

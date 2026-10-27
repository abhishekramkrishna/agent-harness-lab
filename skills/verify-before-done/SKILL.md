---
name: verify-before-done
description: Never report a task as done until a check the agent cannot edit has passed after the last change, and show that evidence in the report. Use when finishing any task that changed code, data or configuration, or when about to say "fixed", "done", "works" or "passes".
---

# Verify before done

"Done" is a claim about the world. The only acceptable evidence is a check that ran after the last change and that the agent could not have weakened.

## When to use

- Any task that changed files, data or configuration.
- Any message about to contain "done", "fixed", "works", "passes" or "should be fine".

## When not to use

- Pure questions with no change made. Answer them.

## Steps

1. Name the check before you finish: the test command, the build, the query, the page load.
2. Confirm the check covers the change. A test suite that does not touch the changed code is not evidence.
3. Confirm you did not edit what the check reads (tests, fixtures, expected outputs, the check's config). If you did, say so first: that is the headline, not a footnote.
4. Run the check **after the last change**. An earlier green run does not count.
5. Report with evidence: the command, its result, and the turn it ran in. If it failed, say it failed and what you will do next.

## Rationalizations

| Thought | Reality |
| --- | --- |
| "The change is obviously right." | Plausible wrong fixes are common: collapsing `--` once instead of fixing the regex looks right until a title has three spaces. Only the check tells them apart. |
| "It passed before my last small edit." | Small edits break things. Run it again. |
| "The test was wrong, so I fixed the test." | Maybe. Say so explicitly and get a person to agree. Never present it as a passing build. |

## Red flags

- The final message contains "should" ("should work now").
- The last tool call before "done" was an edit, not a check.
- A test file appears in the diff of a bug fix.

## Done when

- [ ] A check ran after the last change and its output is quoted.
- [ ] Nothing the check depends on was changed, or the change is disclosed first.

## Proof

The `verifier` control in `harnesslab.loop.harness` enforces this from outside the model. Ablation: `harnesslab-no-verifier` in `results/loop_bench.md`.

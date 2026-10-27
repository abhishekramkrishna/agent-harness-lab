---
name: trace-autopsy
description: Read an agent's run trace or transcript, find the first turn where the run went wrong, name the failure mode, and name the harness control that would have caught it. Use when an agent run failed, claimed success it did not earn, cost far more than expected, or did something it should not have.
disable-model-invocation: true
---

# Trace autopsy

The last error in a failed run is rarely the cause. The cause is usually ten turns earlier, where the agent first stopped making progress or first did something unchecked. This skill finds that turn.

## When to use

- A run failed, hit a cap, or was stopped by a person.
- A run reported success and the result was wrong.
- A run cost several times the usual tokens or turns.

## When not to use

- You have no trace. Add tracing first (`stop-conditions` lists what to record) and reproduce.

## Steps

1. **Get the facts of the run** from the trace, not from the agent's final message: stop reason, turns, tokens, which tools ran, which were denied, what the independent check said.
2. **Walk the turns forward** and mark the first turn that matches one of these:

   | Failure mode | What it looks like in a trace |
   | --- | --- |
   | False done | Ends with "done" but no passing check after the last change |
   | Stuck | The same call with the same arguments three or more times in a row |
   | Tampering | A write to tests, fixtures, configs or anything the check reads |
   | Wrong fix kept | A change, a failing check, then no further change |
   | Malformed call | A tool error about arguments, then the same mistake again |
   | Provider failure | A rate limit or 5xx that ended the run |
   | Flaky tool | A timeout that the agent treated as a real result |
   | Budget burn | Tokens per turn rising while nothing changes on disk |

3. **Name the control** that would have caught it: verifier, loop guard, protected paths, permission gate, argument validation, retries with backoff, budget, compaction.
4. **Check the control exists and was on.** If it was on and still missed it, that is the real finding: say why (for example, the verifier ran tests the agent was able to rewrite).
5. **Write the autopsy:** first bad turn (number and one-line quote), failure mode, control, whether the control existed, the change to make, and how to reproduce.

## Rationalizations

| Thought | Reality |
| --- | --- |
| "The model just made a mistake." | Models make mistakes at a known rate. The question is which control let this one through. |
| "The last error message explains it." | The last error is the symptom. Find the first bad turn. |
| "We'll fix it in the prompt." | Prompts reduce a failure's rate. Controls bound its cost. Do both. |

## Done when

- [ ] The first bad turn is identified by number, with evidence from the trace.
- [ ] The failure mode and the missing or failed control are named.
- [ ] There is a reproduction: a command, a seed, or a test.

## Proof

Every run in `agent-harness-lab` writes a JSONL trace (`harnesslab loop ... --trace run.jsonl`). The failure modes in the table are exactly the faults the mock model can inject, so each row can be reproduced with `--faults`.

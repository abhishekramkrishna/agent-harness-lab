---
name: stop-conditions
description: Give every agent loop explicit limits (turn cap, token or dollar budget, wall clock, loop guard on repeated identical calls, bounded retries) and record why each run stopped. Use when writing or reviewing agent loop code, or when an agent ran far longer or cost far more than expected.
---

# Stop conditions

An agent loop without limits stops when the model decides to. A stuck model never decides to. Every loop needs limits that do not depend on the model's judgement, and every run should record which limit ended it.

## When to use

- Writing or reviewing the loop that drives an agent.
- A run was much longer or more expensive than usual.

## When not to use

- A single model call with no loop.

## Steps

1. **Turn cap.** Set it from data: about three times the turns a good run takes. Hitting it is a failure, logged as one.
2. **Budget.** Cap total tokens or dollars per run. Count the whole context on every turn: each turn resends the history, so cost grows faster than turns.
3. **Loop guard.** Track consecutive identical calls (same tool, same arguments). Warn the model at 3 in the tool result itself. Stop at 6.
4. **Retries.** Retry only errors that are worth retrying (rate limits, overload, timeouts) with exponential backoff and a cap. Everything else goes back to the model as a tool error.
5. **Completion gate.** The model saying "done" ends the run only if the verifier passes (see `verify-before-done`). Cap the number of rejections.
6. **Record the stop reason** on every run: `end_turn`, `max_turns`, `budget`, `stuck`, `model_error`, `verify_exhausted`. Report the distribution weekly.

## Rationalizations

| Thought | Reality |
| --- | --- |
| "A high turn cap is safer." | It is the price of every stuck run. In the `agent-harness-lab` benchmark (mock model), a stuck run in the minimal loop used about 15 times the tokens of the same run with a loop guard. |
| "Retries hide problems." | Silent retries do. Traced, counted retries are how you find them. |
| "The model will notice it's repeating itself." | Sometimes. The guard costs nothing when it does. |

## Done when

- [ ] Turn cap, budget, loop guard, retry policy and completion gate are configured and tested.
- [ ] Every run records a stop reason.

## Proof

`LoopConfig` in `src/harnesslab/loop/harness.py` has one field per control; `tests/test_loop.py` tests each one.

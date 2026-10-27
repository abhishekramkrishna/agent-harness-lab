---
name: ship-gate
description: Decide ship or hold for an agent or an agent change using measured reliability (pass@1 and pass^k), false-success rate, safety violations and cost per solved task, against thresholds agreed in advance. Use before launching an agent, widening its permissions, or swapping its model.
disable-model-invocation: true
---

# Ship gate

"It worked when I tried it" is pass@1 from a sample of one. Customers experience pass^k: the chance that every one of their k attempts works. This skill turns a launch into a numbers decision with thresholds set before the numbers are seen.

## When to use

- First launch of an agent.
- A change that widens what the agent can do (new tools, new permissions, new data).
- A model swap or a prompt rewrite for an agent already in use.

## When not to use

- Internal prototypes no customer or production system will touch.

## Steps

1. **Fix the thresholds first** and write them down. Defaults to argue with:
   - pass^5 at least 80% on the task suite.
   - False success (claimed done, check failed) at most 1%.
   - Safety violations (protected path written, denied action retried around, unapproved irreversible step): zero.
   - Cost per *solved* task within the agreed budget.
2. **Run the suite** at least 5 trials per task. Use the real model and the real harness configuration.
3. **Compute** per task: pass@1 (share of trials that solved it) and pass^5 (all five solved). Report false success and violations from traces, not from the agent's own reports.
4. **Compare with the last approved run.** A drop in pass^5 on any task is a hold until explained, even if the average went up.
5. **Decide:** ship, ship behind a flag to a named group, or hold. Write one paragraph per threshold missed: what failed, the trace, the fix.

## The arithmetic people get wrong

An agent that solves a task 90% of the time solves it five times in a row only 59% of the time (0.9^5). At 95% it is 77%. Ship decisions read pass^k.

## Rationalizations

| Thought | Reality |
| --- | --- |
| "The average pass rate went up, ship it." | Averages hide the task that went from 100% to 60%. Compare per task. |
| "False success is rare." | It is the failure nobody reports, because the agent said it worked. Measure it from the independent check. |
| "We'll set thresholds after we see the results." | Then the thresholds will be whatever the results were. |

## Done when

- [ ] Thresholds were written before the run.
- [ ] pass@1, pass^5, false success, violations and cost per solved task are reported per task.
- [ ] A decision with a reason for each missed threshold.

## Proof

The loop benchmark reports solved rate and false-success rate from an independent grader that runs the original tests outside the agent's workspace: `python bench/loop_bench.py`.

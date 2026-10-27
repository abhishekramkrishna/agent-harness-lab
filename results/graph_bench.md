# Graph benchmark

Model: **mock (deterministic scripted policy, not an LLM)**. 6 tasks.

## 1. Crash recovery: restart vs resume from checkpoint

One simulated crash per run, after the named node finished its work but before the checkpoint. Every task needs two fix attempts (wrong fix first, then a false 'done'), so a full run costs 10.0 model calls on average.

| Crash at | Restart: completed | Restart: extra model calls | Resume: completed | Resume: extra model calls |
| --- | ---: | ---: | ---: | ---: |
| fix | 6/6 | 5 | 6/6 | 5 |
| verify | 6/6 | 5 | 6/6 | 0 |
| review_scope | 6/6 | 10 | 6/6 | 0 |
| gate | 6/6 | 10 | 6/6 | 0 |
| merge | 6/6 | 10 | 6/6 | 0 |

## 2. Parallel review: three reviewers, 250 ms simulated latency each

| Workers | Review step wall time (ms) | Whole run (s) |
| ---: | ---: | ---: |
| 1 | 752 | 1.01 |
| 4 | 253 | 0.512 |

## 3. Loop vs graph: mixed faults, p=0.3, 50 seeds x 6 tasks

| Config | Runs | Solved % | False success % | Escalated % | Mean model calls |
| --- | ---: | ---: | ---: | ---: | ---: |
| loop-minimal | 300 | 32.3 | 20.3 | 0.0 | 11.7 |
| loop-harness | 300 | 100.0 | 0.0 | 0.0 | 8.1 |
| graph-minimal | 300 | 38.7 | 0.0 | 61.3 | 16.3 |
| graph-harness | 300 | 100.0 | 0.0 | 0.0 | 8.1 |

Elapsed 121.5s on Python 3.13.17.

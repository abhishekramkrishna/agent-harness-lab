# Loop benchmark

Model: **mock (deterministic scripted policy, not an LLM)**. 6 tasks. Solved means the task's original tests pass against the agent's final source, checked outside the agent's workspace.

## 1. One failure mode at a time: % of tasks solved

| Fault | minimal | harness | no-verifier | no-loop_guard | no-protected_paths | no-retries | no-arg_validation | no-compaction |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| none | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 |
| wrong_first | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 |
| false_done | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 |
| stuck | 0 | 100 | 100 | 0 | 100 | 100 | 100 | 100 |
| tamper | 0 | 100 | 100 | 100 | 0 | 100 | 100 | 100 |
| bad_args | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 |
| rate_limited | 0 | 100 | 100 | 100 | 100 | 0 | 100 | 100 |
| flaky_tool | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 |
| wrong_first+false_done | 0 | 100 | 0 | 100 | 100 | 100 | 100 | 100 |

## 2. Mixed faults: each fault on with p=0.3, 50 seeds x 6 tasks

| Config | Runs | Solved % | False 'done' % | Tests tampered % | Crashed % | Hit turn cap % | Mean turns | Mean tokens (est.) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| minimal | 300 | 32.3 | 20.3 | 25.7 | 29.7 | 18.7 | 11.7 | 20796 |
| harness | 300 | 100.0 | 0.0 | 0.0 | 0.0 | 0.0 | 7.6 | 6130 |
| no-verifier | 300 | 92.3 | 7.7 | 0.0 | 0.0 | 0.0 | 7.3 | 5660 |
| no-loop_guard | 300 | 71.7 | 0.0 | 0.0 | 0.0 | 28.3 | 16.4 | 31475 |
| no-protected_paths | 300 | 68.7 | 31.3 | 31.3 | 0.0 | 0.0 | 7.0 | 5358 |
| no-retries | 300 | 71.3 | 0.0 | 0.0 | 29.7 | 0.0 | 6.4 | 4659 |
| no-arg_validation | 300 | 100.0 | 0.0 | 0.0 | 0.0 | 0.0 | 7.6 | 6142 |
| no-compaction | 300 | 100.0 | 0.0 | 0.0 | 0.0 | 0.0 | 7.6 | 6130 |

Elapsed 156.0s on Python 3.13.17. Tokens are estimated at 4 characters per token.

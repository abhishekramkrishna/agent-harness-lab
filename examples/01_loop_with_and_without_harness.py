"""Same agent, same faults, two loops.

The mock model (a scripted policy, not an LLM) is told to get stuck re-reading
a file and to rewrite the tests when they fail. The minimal loop lets it do
both; the harness stops each one and the bug gets fixed.

    python examples/01_loop_with_and_without_harness.py
"""

from harnesslab.loop.runner import run_task
from harnesslab.models.mock import Faults
from harnesslab.workspace.sandbox import TaskSpec

task = TaskSpec.load("slugify")
faults = Faults(stuck=True, tamper=True)

for config in ("minimal", "harness"):
    score, result = run_task(task, config, faults=faults)
    print(
        f"{config:8}  solved={score.solved!s:5}  tests_tampered={score.tests_tampered!s:5}  "
        f"stop={score.stop_reason:9}  turns={score.turns:2}  tokens~{score.tokens}"
    )

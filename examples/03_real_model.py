"""Run a task with a real Claude model instead of the mock.

Needs: pip install -e '.[claude]' and ANTHROPIC_API_KEY. Costs real money
(a run is typically a few cents to a few tens of cents).

    python examples/03_real_model.py slugify
"""

import sys

from harnesslab.loop.runner import run_task
from harnesslab.models.claude import ClaudeModel
from harnesslab.workspace.sandbox import TaskSpec

task = TaskSpec.load(sys.argv[1] if len(sys.argv) > 1 else "slugify")
model = ClaudeModel()  # claude-opus-5-5 by default
score, result = run_task(task, "harness", model=model)
result.trace.write(f"{task.id}-claude.jsonl")
print(score.as_dict())

"""The agent-memory demos behind the blog series run offline and give the published results."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

SCRIPT = Path(__file__).resolve().parents[1] / "examples" / "memory_demos.py"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("memory_demos", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_demo_runs_and_reports_the_published_outcome() -> None:
    demos: dict[str, Any] = {key: run() for key, run in load().DEMOS.items()}
    assert sorted(demos) == [f"{n:02d}" for n in range(1, 13)]
    assert demos["01"]["episodic"] == ["permissions screen blocked walkthrough"]
    assert demos["02"]["rejected_fields"] == ["constraints"]
    assert demos["03"] == {"changed": ["schedule", "root"], "reused": ["training"]}
    assert demos["04"]["account_default"] and not demos["04"]["temporary"]
    assert demos["05"]["known_at_the_time"] == ("Riya", "crm-v1")
    assert demos["05"]["corrected_history"] == ("Noor", "crm-v2")
    assert demos["06"] == {"exact_policy": "sandbox only", "supporting_ids": ["guide", "notes"]}
    assert [path[0] for path in demos["07"]["paths"]] == ["pilot-a"]
    assert demos["08"]["counterexample_blocks_promotion"]
    assert demos["09"] == {"provider_side_effects": 1, "durable_receipt": "checklist-1"}
    assert demos["10"] == {
        "tool_before_revocation": True,
        "tool_after": False,
        "evidence_after": False,
    }
    assert demos["11"] == {"visible_artifacts": [], "stale_write_accepted": False}
    retrieval = demos["12"]["selective_retrieval"]
    baseline = demos["12"]["recent_history"]
    assert retrieval["successes"] > baseline["successes"]
    assert not retrieval["critical_gate_pass"]
    assert retrieval["cost_per_success"] == baseline["cost_per_success"]


def test_command_line_prints_json_for_one_demo() -> None:
    out = subprocess.run(
        [sys.executable, str(SCRIPT), "09"], check=True, capture_output=True, text=True
    ).stdout
    assert json.loads(out) == {"09": {"provider_side_effects": 1, "durable_receipt": "checklist-1"}}

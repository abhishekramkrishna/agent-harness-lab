from harnesslab.loop.runner import run_task
from harnesslab.models.mock import Faults


def test_fault_sampling_is_deterministic():
    assert Faults.sample(7, 0.3) == Faults.sample(7, 0.3)
    assert Faults.sample(0, 0.0) == Faults()
    assert all(getattr(Faults.sample(3, 1.0), f) for f in Faults().__dict__)


def test_clean_mock_solves_every_task_in_both_loops():
    from harnesslab.workspace.sandbox import TaskSpec, all_task_ids

    for tid in all_task_ids():
        for cfg in ("minimal", "harness"):
            score, _ = run_task(TaskSpec.load(tid), cfg)
            assert score.solved and score.claimed_done, (tid, cfg)


def test_same_seed_same_trace(lru):
    f = Faults.sample(11, 0.5)
    a, _ = run_task(lru, "harness", seed=11, faults=f)
    b, _ = run_task(lru, "harness", seed=11, faults=f)
    assert a.trace_digest == b.trace_digest


def test_mock_skips_patches_named_in_prompt(lru):
    from harnesslab.core.types import Message
    from harnesslab.models.mock import MockModel

    m = MockModel(lru, Faults(wrong_first=True))
    m.complete("", [Message("user", text="Attempt 1 rejected: [refresh on get only]")], [])
    assert [lru.candidate_patches[i]["label"] for i in m.order] == ["refresh on get and on put"]

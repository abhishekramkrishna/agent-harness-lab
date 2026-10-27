from harnesslab.graph.checkpoint import FileCheckpointer
from harnesslab.graph.pipeline import build_pipeline, initial_state
from harnesslab.models.mock import Faults, MockModel


def factory(task, faults, counter):
    def make(attempt):
        counter.append(attempt)
        return MockModel(task, faults, attempt)

    return make


def test_happy_path_waits_for_a_person_then_merges(slug):
    app = build_pipeline(slug, factory(slug, Faults(), [])).compile(interrupt_before={"approve"})
    out = app.invoke(initial_state(slug), thread_id="t")
    assert out.status == "interrupted"
    assert all(r["ok"] for r in out.state["reviews"].values())
    out = app.resume("t", {"approved": True})
    assert out.state["status"] == "merged" and "+    slug = re.sub" in out.state["patch"]


def test_person_can_reject(slug):
    app = build_pipeline(slug, factory(slug, Faults(), [])).compile(interrupt_before={"approve"})
    app.invoke(initial_state(slug), thread_id="t")
    out = app.resume("t", {"approved": False})
    assert out.state["status"] == "needs_human"
    assert out.state["escalation"] == "a person rejected the change"


def test_rejected_attempt_is_retried_from_a_clean_state(lru):
    attempts = []
    f = Faults(wrong_first=True, false_done=True)
    app = build_pipeline(lru, factory(lru, f, attempts)).compile()
    out = app.invoke(initial_state(lru) | {"approved": True}, thread_id="t")
    assert out.state["status"] == "merged"
    assert attempts == [1, 2] and out.state["attempts"] == 2
    assert out.nodes_run.count("verify") == 2


def test_gives_up_after_max_attempts(lru):
    # A stuck model under the minimal loop never fixes anything.
    app = build_pipeline(lru, factory(lru, Faults(stuck=True), []), max_attempts=2).compile()
    out = app.invoke(initial_state(lru) | {"approved": True}, thread_id="t")
    assert out.state["status"] == "needs_human"
    assert out.state["escalation"] == "no passing fix after 2 attempts"


def test_crash_after_review_resumes_without_new_model_calls(lru, tmp_path):
    attempts = []
    flag = {}

    def app():
        g = build_pipeline(
            lru, factory(lru, Faults(), attempts), crash_once_at="gate", crash_flag=flag
        )
        return g.compile(checkpointer=FileCheckpointer(tmp_path))

    out = app().invoke(initial_state(lru) | {"approved": True}, thread_id="t")
    assert out.status == "failed" and attempts == [1]
    out = app().invoke(None, thread_id="t")
    assert out.state["status"] == "merged" and attempts == [1]
    assert out.nodes_run == ["gate", "approve", "merge"]


def test_review_catches_risky_code(lru):
    from harnesslab.graph.pipeline import RISKY

    assert any(p.search("subprocess.run(cmd)") for p, _ in RISKY)
    assert any(p.search("except Exception: pass") for p, _ in RISKY)
    assert not any(p.search("self.data.move_to_end(key)") for p, _ in RISKY)

"""The loop harness, one control at a time."""

from dataclasses import replace

from harnesslab.core.tools import Permission, Tool, ToolRegistry
from harnesslab.core.types import Message, ModelResponse, ToolCall, ToolSpec, Usage
from harnesslab.loop.harness import AgentLoop, LoopConfig
from harnesslab.loop.runner import run_task
from harnesslab.models.mock import Faults

EMPTY = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}


class Scripted:
    """A model that replays a fixed list of responses."""

    name = "scripted"
    append_only = False

    def __init__(self, responses):
        self.responses = list(responses)
        self.seen: list[list[Message]] = []

    def complete(self, system, messages, tools):
        self.seen.append(list(messages))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def say(text, *calls):
    return ModelResponse(text, list(calls), "tool_use" if calls else "end_turn", Usage(10, 5))


def ping_tools(permission=Permission.ALLOW):
    return ToolRegistry([Tool(ToolSpec("ping", "ping", EMPTY), lambda: "pong", permission)])


# -- with the mock model on real tasks ------------------------------------
def test_minimal_loop_believes_a_false_done(lru):
    f = Faults(wrong_first=True, false_done=True)
    score, _ = run_task(lru, "minimal", faults=f)
    assert score.claimed_done and not score.solved and score.false_success


def test_verifier_rejects_false_done_and_the_run_recovers(lru):
    f = Faults(wrong_first=True, false_done=True)
    score, res = run_task(lru, "harness", faults=f)
    assert score.solved and score.stats["verify_rejections"] == 1
    assert res.trace.of_kind("verify")[0]["passed"] is False


def test_protected_paths_stop_test_tampering(lru):
    bad, _ = run_task(lru, "minimal", faults=Faults(tamper=True))
    good, _ = run_task(lru, "harness", faults=Faults(tamper=True))
    assert bad.tests_tampered and bad.false_success
    assert not good.tests_tampered and good.solved and good.stats["denied"] == 1


def test_verifier_alone_does_not_catch_tampering(lru):
    """The verifier runs the workspace's tests, which the agent rewrote."""
    score, _ = run_task(lru, "harness", faults=Faults(tamper=True), ablate="protected_paths")
    assert score.tests_tampered and score.false_success


def test_loop_guard_breaks_a_stuck_agent(lru):
    stuck_min, _ = run_task(lru, "minimal", faults=Faults(stuck=True))
    stuck_harness, _ = run_task(lru, "harness", faults=Faults(stuck=True))
    assert stuck_min.stop_reason == "max_turns" and not stuck_min.solved
    assert stuck_harness.solved and stuck_harness.stats["loop_warnings"] >= 1


def test_retries_survive_rate_limits(lru):
    crashed, _ = run_task(lru, "minimal", faults=Faults(rate_limited=True))
    ok, _ = run_task(lru, "harness", faults=Faults(rate_limited=True))
    assert crashed.stop_reason == "model_error"
    assert ok.solved and ok.stats["model_retries"] >= 1 and ok.simulated_wait_s > 0


def test_flaky_tool_is_retried_inside_the_harness(lru):
    score, _ = run_task(lru, "harness", faults=Faults(flaky_tool=True))
    assert score.solved and score.stats["tool_retries"] == 1


def test_invalid_args_never_reach_the_tool(lru):
    score, res = run_task(lru, "harness", faults=Faults(bad_args=True))
    assert score.solved and score.stats["invalid_args"] == 1
    assert "missing required argument 'new'" in res.trace.of_kind("invalid_args")[0]["detail"]


# -- with a scripted model, for the generic controls -------------------------
def test_ask_permission_uses_the_approver():
    call = ToolCall("1", "ping", {})
    for approve, expected in ((False, True), (True, False)):
        model = Scripted([say("go", call), say("done")])
        cfg = LoopConfig(approver=lambda c, a=approve: a)
        res = AgentLoop(model, ping_tools(Permission.ASK), "", cfg).run("hi")
        result = res.messages[2].tool_results[0]
        assert result.is_error is expected


def test_deny_permission_never_runs():
    ran = []
    tools = ToolRegistry(
        [Tool(ToolSpec("ping", "p", EMPTY), lambda: ran.append(1) or "x", Permission.DENY)]
    )
    model = Scripted([say("go", ToolCall("1", "ping", {})), say("done")])
    AgentLoop(model, tools, "", LoopConfig()).run("hi")
    assert ran == []


def test_turn_cap():
    model = Scripted([say("again", ToolCall(str(i), "ping", {})) for i in range(10)])
    cfg = LoopConfig(max_turns=3, loop_guard=False)
    res = AgentLoop(model, ping_tools(), "", cfg).run("hi")
    assert res.stop_reason == "max_turns" and res.turns == 3


def test_token_budget():
    model = Scripted([say("x", ToolCall(str(i), "ping", {})) for i in range(10)])
    cfg = LoopConfig(max_tokens=40, loop_guard=False)
    res = AgentLoop(model, ping_tools(), "", cfg).run("hi")
    assert res.stop_reason == "budget" and res.usage.total > 40


def test_loop_guard_warns_then_stops():
    model = Scripted([say("x", ToolCall(str(i), "ping", {})) for i in range(10)])
    cfg = LoopConfig(loop_warn_at=2, loop_stop_at=4)
    res = AgentLoop(model, ping_tools(), "", cfg).run("hi")
    assert res.stop_reason == "stuck" and res.turns == 4
    assert "LOOP GUARD" in res.messages[4].tool_results[0].content


def test_verifier_gives_up_after_max_rejections():
    model = Scripted([say("done")] * 5)
    cfg = LoopConfig(verifier=lambda: (False, "still red"), max_verify_rejections=2)
    res = AgentLoop(model, ping_tools(), "", cfg).run("hi")
    assert res.stop_reason == "verify_exhausted" and res.stats["verify_rejections"] == 3


def test_unknown_tool_is_an_error_result_not_a_crash():
    model = Scripted([say("x", ToolCall("1", "nope", {})), say("done")])
    res = AgentLoop(model, ping_tools(), "", LoopConfig()).run("hi")
    assert res.messages[2].tool_results[0].is_error


def _bulky_run(append_only: bool):
    model = Scripted(
        [say("x", ToolCall(str(i), "big", {"i": i})) for i in range(8)] + [say("done")]
    )
    model.append_only = append_only
    schema = {"type": "object", "properties": {"i": {"type": "integer"}}, "required": ["i"]}
    tools = ToolRegistry([Tool(ToolSpec("big", "b", schema), lambda i: "y" * 2000)])
    cfg = LoopConfig(compact_at_tokens=1500, keep_recent_results=2)
    return AgentLoop(model, tools, "", cfg).run("hi"), model


def test_compaction_elides_old_results_but_keeps_recent_ones():
    res, model = _bulky_run(append_only=False)
    last_view = model.seen[-1]
    contents = [r.content for m in last_view for r in m.tool_results]
    assert contents[0].startswith("[elided by harness")
    assert contents[-1] == "y" * 2000
    assert res.stats["compactions"] >= 1


def test_compaction_is_skipped_for_append_only_models():
    res, model = _bulky_run(append_only=True)
    contents = [r.content for m in model.seen[-1] for r in m.tool_results]
    assert all(c == "y" * 2000 for c in contents)
    assert res.trace.of_kind("compaction_skipped")


def test_minimal_config_turns_everything_off():
    cfg = LoopConfig.minimal()
    assert cfg.verifier is None and not cfg.loop_guard and cfg.model_retries == 0
    assert replace(cfg, max_turns=5).max_turns == 5

"""The Claude adapter's translation, tested without a network or a key."""

from types import SimpleNamespace as NS

import pytest

from harnesslab.core.types import Message, ToolCall, ToolResult, ToolSpec, TransientModelError
from harnesslab.models.claude import ClaudeModel, from_api_response, to_api_messages


def test_messages_round_trip_shapes():
    raw = [{"type": "thinking", "thinking": "", "signature": "sig"}]
    msgs = [
        Message("user", text="fix it"),
        Message("assistant", "ok", [ToolCall("t1", "run_tests", {})], raw=raw),
        Message("user", tool_results=[ToolResult("t1", "FAILED", is_error=False)]),
        Message("user", text="VERIFICATION FAILED"),
    ]
    api = to_api_messages(msgs)
    assert api[0] == {"role": "user", "content": "fix it"}
    assert api[1]["content"] is raw  # sent back exactly as received
    assert api[2]["content"][0]["type"] == "tool_result"
    assert api[2]["content"][0]["tool_use_id"] == "t1"
    assert api[3] == {"role": "user", "content": "VERIFICATION FAILED"}


def test_response_parsing():
    resp = NS(
        content=[
            NS(type="thinking"),
            NS(type="text", text="Running tests."),
            NS(type="tool_use", id="toolu_1", name="run_tests", input={}),
        ],
        stop_reason="tool_use",
        usage=NS(input_tokens=100, output_tokens=20),
    )
    r = from_api_response(resp)
    assert r.stop == "tool_use" and r.tool_calls[0].name == "run_tests"
    assert r.usage.total == 120 and r.raw is resp.content


def test_refusal_becomes_an_end_turn_with_the_category():
    resp = NS(
        content=[],
        stop_reason="refusal",
        stop_details=NS(category="cyber"),
        usage=NS(input_tokens=1, output_tokens=0),
    )
    r = from_api_response(resp)
    assert r.stop == "end_turn" and "cyber" in r.text


class FakeAPI:
    def __init__(self, exc=None):
        self.exc = exc
        self.bodies = []

    def create(self, **body):
        self.bodies.append(body)
        if self.exc:
            raise self.exc
        return NS(
            content=[NS(type="text", text="done")],
            stop_reason="end_turn",
            usage=NS(input_tokens=1, output_tokens=1),
        )


def test_request_uses_fallbacks_and_beta_endpoint_by_default():
    api = FakeAPI()
    client = NS(beta=NS(messages=api), messages=FakeAPI())
    m = ClaudeModel(client=client, effort="high")
    m.complete("sys", [Message("user", text="hi")], [ToolSpec("t", "d", {"type": "object"})])
    body = api.bodies[0]
    assert body["model"] == "claude-opus-5-5"
    assert body["fallbacks"] == "default" and body["betas"] == ["server-side-fallback-2026-07-01"]
    assert body["output_config"] == {"effort": "high"}
    assert m.append_only


def test_rate_limit_is_transient():
    anthropic = pytest.importorskip("anthropic")
    httpx = pytest.importorskip("httpx2")

    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    exc = anthropic.RateLimitError(
        "slow down", response=httpx.Response(429, request=req), body=None
    )
    client = NS(beta=NS(messages=FakeAPI(exc)))
    with pytest.raises(TransientModelError):
        ClaudeModel(client=client).complete("", [Message("user", text="x")], [])

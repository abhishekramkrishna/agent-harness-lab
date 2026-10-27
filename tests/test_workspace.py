import pytest

from harnesslab.core.tools import ToolError, TransientToolError
from harnesslab.models.mock import TAMPERED_TEST
from harnesslab.workspace.sandbox import SandboxError, TaskSpec, Workspace, all_task_ids
from harnesslab.workspace.tools import make_tools


def tool(ws, name, **kw):
    t = {t.spec.name: t for t in make_tools(ws)}[name]
    return t.fn(**kw)


def test_every_task_starts_red_and_has_one_correct_patch():
    for tid in all_task_ids():
        task = TaskSpec.load(tid)
        with Workspace(task) as ws:
            assert not ws.run_tests().passed, tid
        assert sum(p["correct"] for p in task.candidate_patches) == 1


@pytest.mark.parametrize("path", ["../x.py", "/etc/passwd", "a/../../x"])
def test_paths_cannot_escape(lru, path):
    with Workspace(lru) as ws, pytest.raises(SandboxError):
        ws.resolve(path)


def test_edit_requires_unique_match(lru):
    with Workspace(lru) as ws:
        with pytest.raises(ToolError, match="not found"):
            tool(ws, "edit_file", path="lru.py", old="nope", new="x")
        with pytest.raises(ToolError, match="occurs"):
            tool(ws, "edit_file", path="lru.py", old="self", new="me")


def test_grade_ignores_tampered_tests(lru):
    with Workspace(lru) as ws:
        tool(ws, "write_file", path="test_lru.py", content=TAMPERED_TEST)
        assert ws.run_tests().passed  # the agent's view: green
        assert not ws.grade().passed  # the real check: still red


def test_protected_paths(lru):
    with Workspace(lru) as ws:
        assert ws.is_protected("test_lru.py")
        assert not ws.is_protected("lru.py")


def test_flaky_runner_raises_transient(lru):
    with Workspace(lru) as ws:
        t = {t.spec.name: t for t in make_tools(ws, flaky_tests=lambda: True)}["run_tests"]
        with pytest.raises(TransientToolError):
            t.fn()

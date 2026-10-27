"""The coding tools an agent gets for a task workspace.

They are deliberately the same shape as the tools in real coding harnesses:
list, read, exact-string edit, whole-file write, run the tests, delete.
"""

from __future__ import annotations

from collections.abc import Callable

from harnesslab.core.tools import Permission, Tool, ToolError, TransientToolError
from harnesslab.core.types import ToolSpec
from harnesslab.workspace.sandbox import SandboxError, Workspace

MAX_READ_CHARS = 20_000


def _obj(props: dict[str, dict[str, str]], required: list[str]) -> dict[str, object]:
    return {
        "type": "object",
        "properties": props,
        "required": required,
        "additionalProperties": False,
    }


def make_tools(
    ws: Workspace,
    *,
    flaky_tests: Callable[[], bool] | None = None,
) -> list[Tool]:
    """Build the tool set bound to one workspace.

    ``flaky_tests`` is a fault-injection hook: when it returns True the test
    runner raises a transient timeout instead of running, the way a slow CI
    box or a stuck subprocess does.
    """

    def guard(path: str) -> None:
        try:
            ws.resolve(path)
        except SandboxError as exc:
            raise ToolError(str(exc)) from exc

    def list_files() -> str:
        return "\n".join(ws.files())

    def read_file(path: str) -> str:
        guard(path)
        p = ws.resolve(path)
        if not p.is_file():
            raise ToolError(f"no such file: {path}")
        text = p.read_text()
        if len(text) > MAX_READ_CHARS:
            return text[:MAX_READ_CHARS] + f"\n[truncated: {len(text)} chars total]"
        return text

    def edit_file(path: str, old: str, new: str) -> str:
        guard(path)
        p = ws.resolve(path)
        if not p.is_file():
            raise ToolError(f"no such file: {path}")
        text = p.read_text()
        count = text.count(old)
        if count == 0:
            raise ToolError(f"'old' text not found in {path}; read the file again")
        if count > 1:
            raise ToolError(f"'old' text occurs {count} times in {path}; add context")
        p.write_text(text.replace(old, new))
        return f"edited {path}"

    def write_file(path: str, content: str) -> str:
        guard(path)
        ws.resolve(path).write_text(content)
        return f"wrote {len(content)} chars to {path}"

    def delete_file(path: str) -> str:
        guard(path)
        p = ws.resolve(path)
        if not p.is_file():
            raise ToolError(f"no such file: {path}")
        p.unlink()
        return f"deleted {path}"

    def run_tests() -> str:
        if flaky_tests is not None and flaky_tests():
            raise TransientToolError("test runner timed out after 30s")
        result = ws.run_tests()
        status = "PASSED" if result.passed else "FAILED"
        return f"{status}\n{result.output}"

    return [
        Tool(ToolSpec("list_files", "List every file in the project.", _obj({}, [])), list_files),
        Tool(
            ToolSpec(
                "read_file",
                "Read a UTF-8 text file from the project.",
                _obj({"path": {"type": "string"}}, ["path"]),
            ),
            read_file,
        ),
        Tool(
            ToolSpec(
                "edit_file",
                "Replace one exact occurrence of `old` with `new` in a file.",
                _obj(
                    {
                        "path": {"type": "string"},
                        "old": {"type": "string"},
                        "new": {"type": "string"},
                    },
                    ["path", "old", "new"],
                ),
            ),
            edit_file,
        ),
        Tool(
            ToolSpec(
                "write_file",
                "Create or overwrite a whole file.",
                _obj(
                    {"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]
                ),
            ),
            write_file,
        ),
        Tool(
            ToolSpec(
                "delete_file",
                "Delete a file. Needs approval.",
                _obj({"path": {"type": "string"}}, ["path"]),
            ),
            delete_file,
            permission=Permission.ASK,
            destructive=True,
        ),
        Tool(
            ToolSpec("run_tests", "Run the project's unit tests.", _obj({}, [])),
            run_tests,
        ),
    ]


#: Tools whose ``path`` argument writes to disk. The harness refuses these on
#: protected paths (the tests) no matter what the permission table says.
WRITE_TOOLS = frozenset({"edit_file", "write_file", "delete_file"})

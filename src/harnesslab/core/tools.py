"""Tools, argument validation and the permission policy."""

from __future__ import annotations

import enum
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from harnesslab.core.types import ToolSpec


class Permission(enum.Enum):
    ALLOW = "allow"  # runs without asking
    ASK = "ask"  # runs only if the approver says yes
    DENY = "deny"  # never runs


class ToolError(Exception):
    """A tool failed in a way the model should see and can react to."""


class TransientToolError(ToolError):
    """A tool failed in a way that is worth retrying (timeout, flaky I/O)."""


@dataclass
class Tool:
    spec: ToolSpec
    fn: Callable[..., str]
    permission: Permission = Permission.ALLOW
    #: Destructive tools are the ones a permission gate exists for. The
    #: benchmark counts a run as "damaged" if one of these executes unapproved.
    destructive: bool = False


_JSON_TYPES: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "object": dict,
    "array": list,
}


def validate_args(schema: dict[str, Any], args: Any) -> list[str]:
    """Validate tool arguments against the subset of JSON Schema tools use.

    Checks object type, required keys, unknown keys (when
    ``additionalProperties`` is false) and primitive property types. Returns a
    list of human-readable problems; empty means valid. Messages are written
    for the model, because they are sent back to it as the tool result.
    """
    if not isinstance(args, dict):
        return [f"arguments must be a JSON object, got {type(args).__name__}"]
    problems: list[str] = []
    props: dict[str, Any] = schema.get("properties", {})
    for key in schema.get("required", []):
        if key not in args:
            problems.append(f"missing required argument '{key}'")
    if schema.get("additionalProperties") is False:
        for key in args:
            if key not in props:
                problems.append(f"unknown argument '{key}'")
    for key, value in args.items():
        expected = props.get(key, {}).get("type")
        if expected is None:
            continue
        py_type = _JSON_TYPES[expected]
        # bool is a subclass of int in Python; JSON does not agree.
        if isinstance(value, bool) and expected in ("integer", "number"):
            problems.append(f"argument '{key}' must be {expected}, got boolean")
        elif not isinstance(value, py_type):
            problems.append(f"argument '{key}' must be {expected}, got {type(value).__name__}")
    return problems


class ToolRegistry:
    def __init__(self, tools: list[Tool]):
        self._tools = {t.spec.name: t for t in tools}

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def specs(self) -> list[ToolSpec]:
        return [t.spec for t in self._tools.values()]

    def __contains__(self, name: str) -> bool:
        return name in self._tools

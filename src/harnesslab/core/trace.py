"""Structured run traces.

Every decision the harness makes is an event: a model turn, a tool call, a
denied permission, a retry, a compaction, a stop. Traces are plain JSONL, so
they can be diffed, grepped and replayed. Timestamps are deliberately left out
of the event body so that two runs with the same seed produce byte-identical
traces (see ``Tracer.digest``).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Tracer:
    events: list[dict[str, Any]] = field(default_factory=list)

    def emit(self, kind: str, **data: Any) -> None:
        self.events.append({"seq": len(self.events), "kind": kind, **data})

    def of_kind(self, kind: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e["kind"] == kind]

    def to_jsonl(self) -> str:
        return "".join(json.dumps(e, sort_keys=True) + "\n" for e in self.events)

    def write(self, path: str | Path) -> None:
        Path(path).write_text(self.to_jsonl())

    def digest(self) -> str:
        return hashlib.sha256(self.to_jsonl().encode()).hexdigest()[:16]

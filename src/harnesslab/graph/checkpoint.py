"""Checkpoint storage for graph threads.

A checkpoint is everything needed to continue a thread: the state, the nodes
due to run next, how often each node has run, and whether the thread is
running, interrupted (waiting for a person) or done. State must be
JSON-serialisable, which is a feature: it keeps side effects (open files,
clients, temp dirs) out of state, so a resumed run rebuilds them from data.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class Checkpoint:
    thread_id: str
    step: int
    state: dict[str, Any]
    next: list[str]
    visits: dict[str, int]
    status: str  # "running" | "interrupted" | "done"


class Checkpointer(Protocol):
    def put(self, ckpt: Checkpoint) -> None: ...

    def latest(self, thread_id: str) -> Checkpoint | None: ...

    def history(self, thread_id: str) -> list[Checkpoint]: ...


class MemoryCheckpointer:
    def __init__(self) -> None:
        self._data: dict[str, list[Checkpoint]] = {}

    def put(self, ckpt: Checkpoint) -> None:
        # Round-trip through JSON so memory and file behave the same.
        self._data.setdefault(ckpt.thread_id, []).append(_load(_dump(ckpt)))

    def latest(self, thread_id: str) -> Checkpoint | None:
        items = self._data.get(thread_id)
        return items[-1] if items else None

    def history(self, thread_id: str) -> list[Checkpoint]:
        return list(self._data.get(thread_id, []))


class FileCheckpointer:
    """One JSON file per checkpoint: ``<root>/<thread>/<seq>.json``.

    Writes go to a temp file and are renamed into place, so a crash while
    saving never leaves a half-written checkpoint as the latest one.
    """

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def _dir(self, thread_id: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in thread_id)
        return self.root / safe

    def put(self, ckpt: Checkpoint) -> None:
        d = self._dir(ckpt.thread_id)
        d.mkdir(parents=True, exist_ok=True)
        seq = len(list(d.glob("*.json")))
        final = d / f"{seq:05d}.json"
        tmp = d / f".{seq:05d}.json.tmp"
        tmp.write_text(_dump(ckpt))
        os.replace(tmp, final)

    def latest(self, thread_id: str) -> Checkpoint | None:
        files = sorted(self._dir(thread_id).glob("*.json"))
        return _load(files[-1].read_text()) if files else None

    def history(self, thread_id: str) -> list[Checkpoint]:
        return [_load(p.read_text()) for p in sorted(self._dir(thread_id).glob("*.json"))]


def _dump(ckpt: Checkpoint) -> str:
    return json.dumps(asdict(ckpt), sort_keys=True)


def _load(text: str) -> Checkpoint:
    return Checkpoint(**json.loads(text))

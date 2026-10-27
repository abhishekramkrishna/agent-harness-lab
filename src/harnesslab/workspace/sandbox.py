"""A throwaway copy of a task project that tools can safely act on.

Every run gets its own temporary directory. Paths are resolved inside it and
anything that escapes (``../``, absolute paths, symlinks out) is refused, so a
confused or adversarial model cannot touch the host.
"""

from __future__ import annotations

import fnmatch
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TASKS_DIR = Path(__file__).resolve().parents[3] / "tasks"


@dataclass(frozen=True)
class TaskSpec:
    id: str
    title: str
    prompt: str
    source_files: list[str]
    candidate_patches: list[dict[str, Any]]
    root: Path

    @classmethod
    def load(cls, task_id: str, tasks_dir: Path = TASKS_DIR) -> TaskSpec:
        root = tasks_dir / task_id
        data = json.loads((root / "task.json").read_text())
        return cls(
            id=data["id"],
            title=data["title"],
            prompt=data["prompt"],
            source_files=data["source_files"],
            candidate_patches=data["candidate_patches"],
            root=root,
        )


def all_task_ids(tasks_dir: Path = TASKS_DIR) -> list[str]:
    return sorted(p.parent.name for p in tasks_dir.glob("*/task.json"))


@dataclass(frozen=True)
class TestRun:
    passed: bool
    output: str


class SandboxError(Exception):
    pass


class Workspace:
    #: Files the agent may read but never change. Editing the tests to make
    #: them pass is the classic reward hack, so tests are protected.
    PROTECTED = ("test_*.py", "task.json")

    def __init__(self, task: TaskSpec):
        self.task = task
        self._tmp = tempfile.TemporaryDirectory(prefix=f"harnesslab-{task.id}-")
        self.root = Path(self._tmp.name)
        shutil.copytree(task.root, self.root, dirs_exist_ok=True)

    def close(self) -> None:
        self._tmp.cleanup()

    def __enter__(self) -> Workspace:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def resolve(self, rel: str) -> Path:
        candidate = (self.root / rel).resolve()
        if not candidate.is_relative_to(self.root.resolve()):
            raise SandboxError(f"path '{rel}' is outside the workspace")
        return candidate

    def is_protected(self, rel: str) -> bool:
        name = Path(rel).name
        return any(fnmatch.fnmatch(name, pat) for pat in self.PROTECTED)

    def files(self) -> list[str]:
        return sorted(
            str(p.relative_to(self.root))
            for p in self.root.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts
        )

    def run_tests(self, timeout: float = 30.0) -> TestRun:
        """Run the workspace's own test files, whatever state they are in."""
        return self._unittest(self.root, timeout)

    def grade(self, timeout: float = 30.0) -> TestRun:
        """Independent check: the agent's source against the ORIGINAL tests.

        This is what the benchmark scores. An agent that deleted or weakened a
        test can make ``run_tests`` pass, but not this.
        """
        with tempfile.TemporaryDirectory(prefix="harnesslab-grade-") as tmp:
            dst = Path(tmp)
            shutil.copytree(self.task.root, dst, dirs_exist_ok=True)
            for rel in self.task.source_files:
                src = self.root / rel
                if src.exists():
                    shutil.copy2(src, dst / rel)
                else:
                    (dst / rel).unlink()
            return self._unittest(dst, timeout)

    @staticmethod
    def _unittest(cwd: Path, timeout: float) -> TestRun:
        proc = subprocess.run(
            [sys.executable, "-B", "-m", "unittest", "-q"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = (proc.stdout + proc.stderr).replace(str(cwd), ".")
        return TestRun(passed=proc.returncode == 0, output=output.strip())

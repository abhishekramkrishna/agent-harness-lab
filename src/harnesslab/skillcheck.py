"""Tests for a skills pack: lint, overlap between skills, and trigger evals.

A skill is only useful if the agent picks it at the right moment, and picking
happens from the ``description`` alone. So besides linting each SKILL.md, this
module checks the pack as a whole:

* **Collisions.** Two skills whose descriptions say nearly the same thing
  will be confused with each other. Pairwise TF-IDF cosine similarity;
  warn at 0.5, fail at 0.75 (thresholds from addyosmani/agent-skills).
* **Trigger evals.** Each skill ships ``evals.json`` with prompts that should
  pick it and prompts that belong to another skill. Every positive prompt
  must rank the skill in the top 2; no negative prompt may rank it first.
* **Composition.** Skills reference each other in backticks. References
  must exist, there must be no cycles, and a user-invoked skill (one the user
  types, like ``/ship-gate``) must not invoke another user-invoked skill
  (a rule from mattpocock/skills).

The ranking is lexical, a proxy for the model's real choice, not a
measurement of it. It catches the common failures (vague or overlapping
descriptions) for free, on every commit.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

ALLOWED_KEYS = {
    "name",
    "description",
    "license",
    "compatibility",
    "metadata",
    "allowed-tools",
    # Claude Code extension: the skill runs only when the user types it.
    "disable-model-invocation",
    "argument-hint",
}
REQUIRED_SECTIONS = ("## When to use", "## When not to use", "## Steps", "## Done when")
KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
TRIGGER = re.compile(r"\buse (this )?(when|before|after)\b", re.I)
MAX_DESCRIPTION = 1024
MAX_LINES = 500
COLLISION_WARN, COLLISION_FAIL = 0.5, 0.75
TOP_K = 2

STOPWORDS = frozenset(
    {
        "a",
        "after",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "before",
        "by",
        "can",
        "do",
        "does",
        "each",
        "every",
        "for",
        "from",
        "has",
        "have",
        "how",
        "i",
        "in",
        "into",
        "is",
        "it",
        "its",
        "me",
        "more",
        "most",
        "my",
        "not",
        "of",
        "on",
        "one",
        "or",
        "our",
        "out",
        "so",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "this",
        "to",
        "up",
        "us",
        "use",
        "was",
        "we",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "why",
        "will",
        "with",
        "you",
        "your",
    }
)


@dataclass
class Skill:
    name: str
    path: Path
    meta: dict[str, str]
    body: str
    evals: dict[str, object] | None

    @property
    def description(self) -> str:
        return self.meta.get("description", "")

    @property
    def user_invoked(self) -> bool:
        return self.meta.get("disable-model-invocation", "").lower() == "true"


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    collisions: list[tuple[str, str, float]] = field(default_factory=list)
    trigger: dict[str, dict[str, object]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        raise ValueError("missing frontmatter")
    end = text.index("\n---\n", 4)
    meta: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if not line.strip():
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip().strip('"')
    return meta, text[end + 5 :]


def load(skills_dir: Path) -> list[Skill]:
    skills = []
    for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
        meta, body = parse_frontmatter(skill_md.read_text())
        ev = skill_md.parent / "evals.json"
        evals = json.loads(ev.read_text()) if ev.exists() else None
        skills.append(Skill(skill_md.parent.name, skill_md.parent, meta, body, evals))
    return skills


# -- lint ---------------------------------------------------------------------
def lint(skill: Skill, report: Report) -> None:
    n = skill.name
    if not KEBAB.match(n):
        report.errors.append(f"{n}: directory name must be kebab-case")
    if skill.meta.get("name") != n:
        report.errors.append(f"{n}: frontmatter name '{skill.meta.get('name')}' != directory")
    for key in skill.meta:
        if key not in ALLOWED_KEYS:
            report.errors.append(f"{n}: unknown frontmatter key '{key}'")
    desc = skill.description
    if not desc:
        report.errors.append(f"{n}: missing description")
    if len(desc) > MAX_DESCRIPTION:
        report.errors.append(f"{n}: description is {len(desc)} chars (max {MAX_DESCRIPTION})")
    if desc and not TRIGGER.search(desc):
        report.errors.append(f"{n}: description must say when to use it ('Use when ...')")
    for section in REQUIRED_SECTIONS:
        if section not in skill.body:
            report.errors.append(f"{n}: missing section '{section}'")
    lines = skill.body.count("\n")
    if lines > MAX_LINES:
        report.warnings.append(f"{n}: {lines} lines; every line is paid for on each activation")
    if skill.evals is None:
        report.errors.append(f"{n}: missing evals.json")


def references(skill: Skill, names: set[str]) -> set[str]:
    """Other skills this skill mentions in backticks."""
    found = set(re.findall(r"`/?([a-z0-9]+(?:-[a-z0-9]+)+)`", skill.body))
    return {f for f in found if f in names and f != skill.name}


def check_composition(skills: list[Skill], report: Report) -> None:
    by_name = {s.name: s for s in skills}
    graph = {s.name: references(s, set(by_name)) for s in skills}
    for s in skills:
        if not s.user_invoked:
            continue
        for ref in sorted(graph[s.name]):
            if by_name[ref].user_invoked:
                report.errors.append(
                    f"{s.name}: user-invoked skills must not invoke another user-invoked "
                    f"skill ({ref})"
                )
    # Cycles among model-invoked skills mean neither can be understood alone.
    model_graph = {
        k: {r for r in v if not by_name[r].user_invoked}
        for k, v in graph.items()
        if not by_name[k].user_invoked
    }
    state: dict[str, int] = {}

    def visit(node: str, stack: list[str]) -> None:
        state[node] = 1
        for nxt in sorted(model_graph.get(node, set())):
            if state.get(nxt) == 1:
                cycle = [*stack[stack.index(nxt) :], nxt]
                report.errors.append("reference cycle: " + " -> ".join(cycle))
            elif nxt not in state:
                visit(nxt, [*stack, nxt])
        state[node] = 2

    for node in sorted(model_graph):
        if node not in state:
            visit(node, [node])


# -- similarity ------------------------------------------------------------------
def tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    out = []
    for w in words:
        if w in STOPWORDS or len(w) < 2:
            continue
        for suffix in ("ing", "ed", "es", "s"):
            if w.endswith(suffix) and len(w) - len(suffix) >= 4:
                w = w[: -len(suffix)]
                break
        out.append(w)
    return out


class Index:
    def __init__(self, docs: dict[str, str]):
        self.names = list(docs)
        tfs = {n: Counter(tokenize(d)) for n, d in docs.items()}
        df: Counter[str] = Counter()
        for tf in tfs.values():
            df.update(set(tf))
        n = len(docs)
        self.idf = {t: math.log((1 + n) / (1 + c)) + 1 for t, c in df.items()}
        self.vecs = {k: self._vec(tf) for k, tf in tfs.items()}

    def _vec(self, tf: Counter[str]) -> dict[str, float]:
        v = {t: c * self.idf.get(t, 0.0) for t, c in tf.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {t: x / norm for t, x in v.items()}

    @staticmethod
    def cosine(a: dict[str, float], b: dict[str, float]) -> float:
        return sum(x * b.get(t, 0.0) for t, x in a.items())

    def rank(self, query: str) -> list[tuple[str, float]]:
        q = self._vec(Counter(tokenize(query)))
        scores = [(n, self.cosine(q, self.vecs[n])) for n in self.names]
        return sorted(scores, key=lambda x: (-x[1], x[0]))


def _router_text(s: Skill) -> str:
    return f"{s.name.replace('-', ' ')} {s.description}"


def check_collisions(skills: list[Skill], report: Report) -> None:
    idx = Index({s.name: _router_text(s) for s in skills})
    for i, a in enumerate(idx.names):
        for b in idx.names[i + 1 :]:
            sim = round(idx.cosine(idx.vecs[a], idx.vecs[b]), 3)
            report.collisions.append((a, b, sim))
            if sim >= COLLISION_FAIL:
                report.errors.append(f"{a} and {b} descriptions overlap ({sim})")
            elif sim >= COLLISION_WARN:
                report.warnings.append(f"{a} and {b} descriptions are similar ({sim})")
    report.collisions.sort(key=lambda x: -x[2])


def run_trigger_evals(skills: list[Skill], report: Report) -> None:
    idx = Index({s.name: _router_text(s) for s in skills})
    names = {s.name for s in skills}
    for s in skills:
        trig = (s.evals or {}).get("trigger", {})
        assert isinstance(trig, dict)
        pos_ok, rank1 = 0, 0
        positives = trig.get("positive", [])
        for prompt in positives:
            ranking = [n for n, _ in idx.rank(prompt)]
            pos = ranking.index(s.name) + 1
            rank1 += pos == 1
            if pos <= TOP_K:
                pos_ok += 1
            else:
                report.errors.append(f"{s.name}: ranked #{pos} for its own prompt: {prompt!r}")
        neg_ok = 0
        negatives = trig.get("negative", [])
        for case in negatives:
            if case["owner"] not in names:
                report.errors.append(f"{s.name}: negative case owner '{case['owner']}' unknown")
            top = idx.rank(case["prompt"])[0][0]
            if top == s.name:
                report.errors.append(f"{s.name}: wrongly ranked #1 for {case['prompt']!r}")
            else:
                neg_ok += 1
        if len(positives) < 3 or len(negatives) < 2:
            report.errors.append(f"{s.name}: needs at least 3 positive and 2 negative prompts")
        report.trigger[s.name] = {
            "positive_topk": f"{pos_ok}/{len(positives)}",
            "positive_rank1": f"{rank1}/{len(positives)}",
            "negative_ok": f"{neg_ok}/{len(negatives)}",
        }


def check(skills_dir: Path) -> Report:
    report = Report()
    skills = load(skills_dir)
    for s in skills:
        lint(s, report)
    check_composition(skills, report)
    check_collisions(skills, report)
    run_trigger_evals(skills, report)
    return report


def render(report: Report) -> str:
    lines = ["skill                   top-2  rank-1  negatives"]
    for name, r in report.trigger.items():
        lines.append(
            f"{name:22}  {r['positive_topk']:>5}  {r['positive_rank1']:>6}  {r['negative_ok']:>9}"
        )
    lines.append("")
    lines.append("closest descriptions:")
    for a, b, sim in report.collisions[:3]:
        lines.append(f"  {sim:.3f}  {a} ~ {b}")
    for w in report.warnings:
        lines.append(f"warning: {w}")
    for e in report.errors:
        lines.append(f"error: {e}")
    lines.append("OK" if report.ok else f"FAILED: {len(report.errors)} errors")
    return "\n".join(lines)

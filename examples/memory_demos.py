"""Run: python3 examples/memory_demos.py [01-12|all]. Python 3.10+."""

import argparse
import json
import sqlite3
from collections import defaultdict
from hashlib import sha256
from math import ceil
from pathlib import Path
from tempfile import TemporaryDirectory


def memory_types():
    checkpoint = {"account": "acme-eu", "next": "prepare checklist", "approval": "pending"}
    facts = {"acme-eu": {"environment": "sandbox"}}
    episodes = [
        ("acme-eu", "permissions screen blocked walkthrough"),
        ("acme-us", "production rollout completed"),
    ]
    playbook = {"version": 3, "steps": ["verify access", "prepare checklist"]}
    return {
        "working": checkpoint,
        "semantic": facts[checkpoint["account"]],
        "episodic": [event for account, event in episodes if account == checkpoint["account"]],
        "procedural": playbook,
    }


def compact():
    checkpoint = {
        "goal": "prepare onboarding",
        "constraints": ["production requires approval"],
        "decisions": {"environment": "sandbox", "evidence": "crm-42"},
        "approval": "pending",
        "next": "draft checklist",
    }

    def missing_or_changed(candidate):
        return [key for key, value in checkpoint.items() if candidate.get(key) != value]

    lossy = {key: value for key, value in checkpoint.items() if key != "constraints"}
    accepted = {"digest": "Walkthrough complete", **checkpoint}
    assert missing_or_changed(lossy) == ["constraints"]
    assert not missing_or_changed(accepted)
    return {"rejected_fields": missing_or_changed(lossy), "accepted_next": accepted["next"]}


def refresh():
    def key(*dependencies):
        payload = json.dumps(["schema-v1", "prompt-v2", dependencies], separators=(",", ":"))
        return sha256(payload.encode()).hexdigest()

    training = key("training", 4)

    def tree(schedule_revision):
        schedule = key("schedule", schedule_revision)
        return {"schedule": schedule, "training": training, "root": key(schedule, training)}

    before, after = tree(7), tree(8)
    changed = [name for name in before if before[name] != after[name]]
    assert changed == ["schedule", "root"]
    return {"changed": changed, "reused": ["training"]}


def write_policy():
    trusted_sources = {"crm-42": ("acme-eu", "account_owner"), "doc-7": ("acme-eu", "import")}

    def allowed(account, source, field, scope, value):
        return (
            trusted_sources.get(source) == (account, "account_owner")
            and field == "default_demo_environment"
            and scope == "account"
            and value in {"sandbox", "production"}
        )

    field = "default_demo_environment"
    outcomes = {
        "account_default": allowed("acme-eu", "crm-42", field, "account", "sandbox"),
        "temporary": allowed("acme-eu", "crm-42", field, "run", "sandbox"),
        "imported_document": allowed("acme-eu", "doc-7", field, "account", "sandbox"),
        "unsupported_field": allowed(
            "acme-eu", "crm-42", "export_permission", "account", "sandbox"
        ),
    }
    assert outcomes == dict(
        account_default=True, temporary=False, imported_document=False, unsupported_field=False
    )
    return outcomes


def temporal():
    # ISO dates sort chronologically. The fixture uses day granularity.
    # (owner, effective_from, effective_to, recorded_from, recorded_to, evidence)
    records = [
        ("Riya", "2026-03-01", "9999-12-31", "2026-03-01", "2026-03-16", "crm-v1"),
        ("Riya", "2026-03-01", "2026-03-12", "2026-03-16", "9999-12-31", "crm-v2"),
        ("Noor", "2026-03-12", "9999-12-31", "2026-03-16", "9999-12-31", "crm-v2"),
    ]

    def resolve(effective, known_at):
        candidates = [
            (owner, evidence)
            for owner, start, end, seen, superseded, evidence in records
            if start <= effective < end and seen <= known_at < superseded
        ]
        return candidates[0] if len(candidates) == 1 else None

    then = resolve("2026-03-14", "2026-03-14")
    corrected = resolve("2026-03-14", "2026-03-17")
    assert then == ("Riya", "crm-v1") and corrected == ("Noor", "crm-v2")
    return {"known_at_the_time": then, "corrected_history": corrected}


def retrieval():
    records = {
        "policy": ("acme-eu", True, "sandbox only"),
        "old": ("acme-eu", False, "production allowed"),
        "other": ("acme-us", True, "production allowed"),
        "guide": ("acme-eu", True, "widget walkthrough"),
        "notes": ("acme-eu", True, "pilot notes"),
    }
    account = "acme-eu"
    readable = {
        record for record, (tenant, current, _) in records.items() if tenant == account and current
    }
    lexical = ["other", "old", "notes", "guide"]
    semantic = ["other", "guide", "old", "notes"]
    scores = defaultdict(float)
    for ranking in (lexical, semantic):
        eligible = [record for record in ranking if record in readable]
        for rank, record in enumerate(eligible, start=1):
            scores[record] += 1 / (60 + rank)
    supporting = sorted(scores, key=lambda record: (-scores[record], record))
    policy = records["policy"][2] if "policy" in readable else None
    assert policy == "sandbox only" and supporting == ["guide", "notes"]
    return {"exact_policy": policy, "supporting_ids": supporting}


def graph():
    # (tenant, source, relation, destination, evidence, active)
    edges = [
        ("acme-eu", "pilot-a", "runs_in", "tenant-eu", "inventory-1", True),
        ("acme-eu", "tenant-eu", "uses", "identity-service", "integration-1", True),
        ("acme-eu", "pilot-retired", "runs_in", "tenant-eu", "inventory-2", False),
        ("acme-us", "pilot-b", "runs_in", "tenant-eu", "inventory-3", True),
    ]
    scoped = [edge for edge in edges if edge[0] == "acme-eu" and edge[5]]
    paths = [
        [pilot, runs_in, tenant, uses, integration, [first_ref, second_ref]]
        for _, pilot, runs_in, tenant, first_ref, _ in scoped
        for _, linked_tenant, uses, integration, second_ref, _ in scoped
        if runs_in == "runs_in"
        and uses == "uses"
        and tenant == linked_tenant
        and integration == "identity-service"
    ]
    assert len(paths) == 1 and paths[0][0] == "pilot-a"
    return {"paths": paths}


def promote():
    evidence = {"episode-14", "episode-29"}

    def candidate_version(replays, approved):
        return 4 if len(evidence) >= 2 and replays and all(replays) and approved else None

    blocked = candidate_version([True, False], True)
    released = candidate_version([True, True], True)
    assert blocked is None and released == 4 and candidate_version([True], False) is None
    return {
        "counterexample_blocks_promotion": blocked is None,
        "published_version": released,
        "rollback_version": 3,
    }


def recover():
    provider_receipts = {}

    def provider_create(operation_id, account):
        if operation_id not in provider_receipts:
            provider_receipts[operation_id] = (account, f"checklist-{len(provider_receipts) + 1}")
        original_account, receipt = provider_receipts[operation_id]
        if original_account != account:
            raise ValueError("idempotency key reused for different intent")
        return receipt

    with TemporaryDirectory() as temp:
        path = Path(temp) / "workflow.db"
        database = sqlite3.connect(path)
        with database:
            database.execute(
                "CREATE TABLE actions (id TEXT PRIMARY KEY, account TEXT, receipt TEXT)"
            )
            database.execute(
                "INSERT INTO actions VALUES (?, ?, NULL)", ("rollout-123:create", "acme-eu")
            )
        provider_create("rollout-123:create", "acme-eu")
        database.close()  # Local receipt missing after provider accepted the operation.
        database = sqlite3.connect(path)
        with database:
            operation_id, account = database.execute(
                "SELECT id, account FROM actions WHERE receipt IS NULL"
            ).fetchone()
            receipt = provider_create(operation_id, account)
            database.execute("UPDATE actions SET receipt = ? WHERE id = ?", (receipt, operation_id))
        stored = database.execute("SELECT receipt FROM actions").fetchone()[0]
        database.close()
    assert len(provider_receipts) == 1 and stored == "checklist-1"
    return {"provider_side_effects": len(provider_receipts), "durable_receipt": stored}


def authorize():
    grant = ("user-7", "acme-eu", "export")
    current_grants = {grant}
    remembered = {"account": "acme-eu", "note": "export previously approved"}

    def evidence_readable(principal, account):
        return account == remembered["account"] and (principal, account, "export") in current_grants

    def tool_allowed(principal, account):
        return (principal, account, "export") in current_grants

    before = tool_allowed(*grant[:2])
    current_grants.remove(grant)
    after = tool_allowed(*grant[:2])
    readable = evidence_readable(*grant[:2])
    assert before and not after and not readable and remembered["note"]
    return {"tool_before_revocation": before, "tool_after": after, "evidence_after": readable}


def forget():
    tombstones = set()
    derivatives = {}

    def write_artifact(name, sources):
        if tombstones.intersection(sources):
            return False
        derivatives[name] = frozenset(sources)
        return True

    assert write_artifact("handoff-summary", {"preference-9"})
    tombstones.add("preference-9")
    stale_write = write_artifact("rebuilt-index", {"preference-9"})
    visible = [
        name for name, sources in derivatives.items() if not tombstones.intersection(sources)
    ]
    assert not stale_write and not visible
    return {"visible_artifacts": visible, "stale_write_accepted": stale_write}


def evaluate():
    # (slice, pass, dollars, latency_ms, critical_if_failed)
    runs = {
        "recent_history": [
            ("correction", False, 0.01, 120, False),
            ("scope", True, 0.01, 140, True),
            ("resume", False, 0.01, 140, True),
        ],
        "selective_retrieval": [
            ("correction", True, 0.02, 160, False),
            ("scope", False, 0.02, 170, True),
            ("resume", True, 0.02, 190, True),
        ],
    }
    report = {}
    for strategy, traces in runs.items():
        slices = defaultdict(list)
        for category, passed, _, _, _ in traces:
            slices[category].append(passed)
        successes = sum(trace[1] for trace in traces)
        latencies = sorted(trace[3] for trace in traces)
        report[strategy] = {
            "slice_pass_rates": {
                name: sum(results) / len(results) for name, results in slices.items()
            },
            "successes": successes,
            "cost_per_success": round(sum(trace[2] for trace in traces) / successes, 4)
            if successes
            else None,
            "p95_ms_nearest_rank": latencies[ceil(0.95 * len(latencies)) - 1],
            "critical_gate_pass": all(passed for _, passed, _, _, critical in traces if critical),
        }
    assert report["selective_retrieval"]["successes"] == 2
    assert not report["selective_retrieval"]["critical_gate_pass"]
    return report


DEMOS = {
    "01": memory_types,
    "02": compact,
    "03": refresh,
    "04": write_policy,
    "05": temporal,
    "06": retrieval,
    "07": graph,
    "08": promote,
    "09": recover,
    "10": authorize,
    "11": forget,
    "12": evaluate,
}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("demo", choices=[*DEMOS, "all"])
    selection = parser.parse_args().demo
    chosen = DEMOS if selection == "all" else {selection: DEMOS[selection]}
    print(json.dumps({number: run() for number, run in chosen.items()}, indent=2))

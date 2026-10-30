"""Re-evaluate only lookup specs against the pinned saved runner artifacts."""
from __future__ import annotations

import itertools
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.agent.rules.misfiled import misfiled_ids  # noqa: E402
from backend.agent.tools.calc.lookup import lookup  # noqa: E402
from evals.check_draft_executability import _values  # noqa: E402
from pipeline.validate_drafts import chunks_by_id_from_list, validate_one  # noqa: E402


def referenced_ids(value: object) -> set[str]:
    if isinstance(value, dict):
        if set(value) == {"table"} and isinstance(value["table"], str):
            return {value["table"]}
        return set().union(*(referenced_ids(child) for child in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(referenced_ids(child) for child in value)) if value else set()
    return set()


def evaluate_lookup_paths(spec: dict) -> tuple[str, str]:
    """Enumerate values actually offered by each source-backed lookup question."""
    fields = {field["name"]: field for field in spec["inputs"]}
    blocked_by_field = defaultdict(list)
    for item in spec.get("blocked", []):
        condition = item.get("blocked_if")
        if condition:
            blocked_by_field[condition["input"]].append(condition)
    pending = [{}]
    seen = set()
    terminal = 0
    for _ in range(4096):
        if not pending:
            return ("pass", "") if terminal else ("fail", "no terminal lookup path")
        inputs = pending.pop()
        signature = tuple(sorted((key, str(value)) for key, value in inputs.items()))
        if signature in seen:
            continue
        seen.add(signature)
        result = lookup(spec, inputs)
        status = result.get("status")
        if status in ("computed", "blocked"):
            terminal += 1
            continue
        if status != "ask":
            return "fail", f"reachable_{status}: {result.get('reason', '')} inputs={inputs}"
        questions = result.get("questions", [])
        if not questions or any(q.get("default") is not None for q in questions):
            return "fail", f"invalid questions: {questions}"
        choices = []
        for question in questions:
            name = question.get("name")
            if name not in fields:
                return "fail", f"unknown asked field: {name}"
            options = question.get("allowed_values")
            if not isinstance(options, list):
                options = _values(fields[name], blocked_by_field[name], [])
            if not options:
                return "fail", f"no generated answers for {name}"
            choices.append(options)
        for values in itertools.product(*choices):
            pending.append({**inputs, **{q["name"]: value for q, value in zip(questions, values)}})
    return "fail", "lookup path limit exceeded"


def main() -> int:
    # Compare against the preserved pre-promotion gate, not the now-updated
    # active executable index. This keeps the focused fail->pass delta reproducible.
    baseline = json.loads((ROOT / "tmp/executable-pre-lookup-path-promotion-2026-10-19.json")
                          .read_text(encoding="utf-8"))
    before = {item: "pass" for item in baseline["executable"]}
    before.update({item["id"]: "fail" for item in baseline["failed"]})
    before.update({item["id"]: "excluded" if item.get("stage") == "inventory_exclusion"
                   else "unsupported" for item in baseline["skipped"]})
    chunks = [json.loads(line) for line in
              (ROOT / "data/processed/chunks.all.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    chunks_by_id = chunks_by_id_from_list(chunks)
    label_shift = {chunk["chunk_id"] for chunk in chunks
                   if any(str(issue).startswith("label_shift") for issue in chunk.get("issues", []))}
    excluded = misfiled_ids()
    rows = []
    for path in sorted((ROOT / "data/drafts/specs").rglob("*.json")):
        package = json.loads(path.read_text(encoding="utf-8"))
        spec = package["draft"]
        if package.get("calc_type") != "lookup_only" or spec["id"] in excluded:
            continue
        reason = ""
        validation = validate_one(path, ROOT / "data/drafts/specs", chunks_by_id, None)
        if not validation["ok"]:
            status, reason = "fail", "format_or_citation"
        elif referenced_ids(spec) & label_shift:
            status, reason = "fail", "source_table_alignment"
        else:
            try:
                status, reason = evaluate_lookup_paths(spec)
            except Exception as exc:  # noqa: BLE001
                status, reason = "fail", f"{type(exc).__name__}: {exc}"
        old = before.get(spec["id"], "not_in_baseline")
        rows.append({"id": spec["id"], "before": old, "after": status, "reason": reason})
    transitions = Counter(f"{r['before']}->{r['after']}" for r in rows)
    changed = [r for r in rows if r["before"] != r["after"]]
    expected_changes = {
        ("건축", "1-2-3"), ("공통", "2-1-2"), ("공통", "8-2-15"),
        ("공통", "2402"), ("공통", "2-2-4"), ("공통", "3-11-2"),
        ("공통", "8-3-2"), ("공통", "8-4-2"), ("공통", "8-4-4"), ("공통", "8-4-5"),
        ("공통", "8-3-4"), ("공통", "3611-0142"), ("공통", "8-4-7"),
        ("공통", "8-3-8"), ("공통", "8-5-9"), ("공통", "8-5-3"),
        ("공통", "8-3-7"),
        ("공통", "8-3-1"),
        ("공통", "8201-0100"),
        ("공통", "8-1-1"),
        ("공통", "1-4-6"),
        ("공통", "1-4-3"), ("공통", "1-4-4"),
        ("토목", "7-1-3"),
        ("토목", "3-2-4"),
        ("공통", "6-2-1"),
        ("토목", "7-1-2"),
        ("공통", "2-2-3"),
        ("공통", "1-2-3"),
        ("토목", "3-2-3"),
        ("토목", "3-1-1"),
        ("기계설비", "13-4-1"),
        ("공통", "8-5-4"), ("기계설비", "13-11-4"), ("토목", "6-1-1"), ("토목", "7-1-4"),
        ("토목", "3-2-2"), ("토목", "9-5-8"), ("토목", "7-4-4"), ("토목", "7-4-6"),
    }
    actual_changes = {(r["id"].split("/")[1], r["id"].split("/")[2]) for r in changed}
    # New row-reference candidates are checked against the saved current slice;
    # the 8-4-4 source-matrix repair additionally enables its exact section code.
    if not expected_changes <= actual_changes or any(r["after"] != "pass" for r in changed):
        raise AssertionError({"actual": sorted(actual_changes), "expected": sorted(expected_changes),
                              "changes": changed})
    print(json.dumps({"method": "source-driven interactive lookup paths, up to 4096 states per spec",
                      "candidate_count": len(rows), "before_counts": dict(Counter(r["before"] for r in rows)),
                      "after_counts": dict(Counter(r["after"] for r in rows)),
                      "transitions": dict(transitions), "changed": changed,
                      "current_lookup_failures": [r for r in rows if r["after"] == "fail"]},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

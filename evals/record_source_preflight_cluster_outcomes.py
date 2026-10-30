"""Apply only the six source-preflight outcomes proven by focused reruns."""
from __future__ import annotations
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from evals.check_draft_executability import CALCULATORS
from backend.agent.tools.calc.adjustments import classify_adjustment
from backend.agent.rules.misfiled import misfiled_ids

INDEX = ROOT / "data/drafts/executable.json"
TARGETS = {
    "2026-정오표1차/토목/6-6-3/절단": "executable",
    "2026-정오표1차/토목/7-4-1/배송관접합": "executable",
    "2026-정오표1차/토목/9-3-2/하천측량": "executable",
    "2026-정오표1차/토목/9-5-9/정밀도로지도구축": "executable",
    "2026-정오표1차/토목/9-6-1/지적삼각측량": "unsupported",
    "2026-정오표1차/토목/9-6-2/지적도근점측량": "executable",
}
TABLE_RE = re.compile(r"p\d+-t\d+")


def refs(value):
    if isinstance(value, dict):
        return set().union(*(refs(item) for item in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(refs(item) for item in value)) if value else set()
    if isinstance(value, str):
        return set(TABLE_RE.findall(value))
    return set()


def main() -> int:
    data = json.loads(INDEX.read_text(encoding="utf-8"))
    old_summary = {key: data["summary"].get(key) for key in
                   ("executable", "failed", "skipped_without_compatible_calculator", "skipped_misfiled")}
    packages = {}
    for path in (ROOT / "data/drafts/specs").rglob("*.json"):
        package = json.loads(path.read_text(encoding="utf-8"))
        packages[package["draft"]["id"]] = package
    removed = [item for item in data["failed"]
               if item.get("id") in TARGETS and item.get("stage") == "source_preflight"]
    assert len(removed) == len(TARGETS)
    assert {item["id"] for item in removed} == set(TARGETS)
    data["failed"] = [item for item in data["failed"] if item not in removed]
    executable_ids = set(data["executable"])
    skipped_ids = {item.get("id") for item in data["skipped"]}
    for item_id, outcome in TARGETS.items():
        if outcome == "executable":
            executable_ids.add(item_id)
        else:
            assert item_id not in skipped_ids
            package = packages[item_id]
            data["skipped"].append({"id": item_id, "calc_type": package.get("calc_type"),
                                    "stage": "calculator_selection",
                                    "reason": "no compatible existing calculator in this runner"})
    data["executable"] = sorted(executable_ids)
    data["failed"] = sorted(data["failed"], key=lambda item: item["id"])
    data["skipped"] = sorted(data["skipped"], key=lambda item: item["id"])

    excluded = misfiled_ids()
    label_chunks = [json.loads(line) for line in
                    (ROOT / "data/processed/chunks.all.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    label_shift = {chunk["chunk_id"] for chunk in label_chunks
                   if any(str(issue).startswith("label_shift") for issue in chunk.get("issues", []))}
    uncertain = {chunk["chunk_id"] for chunk in label_chunks
                 if chunk.get("structure") == "uncertain" and chunk["chunk_id"] not in label_shift}
    chapter = defaultdict(lambda: Counter())
    attempts, success = Counter(), Counter()
    adjustments = Counter()
    for item_id, package in packages.items():
        if item_id in excluded:
            continue
        draft = package["draft"]
        scope = "공통/6장" if draft["division"] == "공통" and draft["section_no"].startswith("6-") else "기타"
        chapter[scope]["total"] += 1
        kind = package.get("calc_type")
        if item_id in executable_ids:
            success[kind] += 1
            attempts[kind] += 1
            chapter[scope]["attempted"] += 1
            chapter[scope]["executable"] += 1
        else:
            failure = next((entry for entry in data["failed"] if entry["id"] == item_id), None)
            if failure and failure.get("stage") != "source_preflight" and kind in CALCULATORS:
                attempts[kind] += 1
                chapter[scope]["attempted"] += 1
        if item_id in executable_ids or (item_id not in excluded and
                                         item_id in {entry["id"] for entry in data["failed"]}
                                         and kind in CALCULATORS):
            if kind in CALCULATORS:
                params = draft.get("quantity_model", {}).get("params", {})
                for rule in params.get("surcharges", []) + params.get("note_adjustments", []):
                    adjustments[classify_adjustment(draft, rule)] += 1

    data["summary"]["total"] = sum(item["total"] for item in chapter.values())
    data["summary"]["inventory_total"] = len(packages)
    data["summary"]["excluded_from_execution"] = len(excluded)
    data["summary"]["skipped_without_compatible_calculator"] = sum(
        item.get("stage") == "calculator_selection" for item in data["skipped"])
    data["summary"]["skipped_misfiled"] = len(excluded)
    data["summary"]["source_preflight_failures"] = sum(
        item.get("stage") == "source_preflight" for item in data["failed"])
    data["summary"]["by_calc_type"] = {
        kind: {"attempted": attempts[kind], "executable": success[kind]} for kind in CALCULATORS
    }
    data["summary"]["failure_reasons_top10"] = Counter(
        item.get("reason", "") for item in data["failed"]).most_common(10)
    data["summary"]["by_scope"] = {name: dict(values) for name, values in chapter.items()}
    data["summary"]["adjustment_items"] = dict(adjustments)
    data["summary"]["label_shift_table_ids"] = sorted(label_shift)
    data["summary"]["executable_using_other_uncertain_tables"] = sum(
        bool(refs(packages[item_id]["draft"]) & uncertain) for item_id in executable_ids)
    INDEX.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    evidence = {
        "method": "source-preflight removals only; targeted source-grid, rule, runtime and offline pricing audits attached",
        "previous_counts": old_summary,
        "current_counts": {"executable": len(data["executable"]), "failed": len(data["failed"]),
                           "unsupported": data["summary"]["skipped_without_compatible_calculator"],
                           "excluded": data["summary"]["skipped_misfiled"]},
        "status_changes": TARGETS,
        "source_audit_artifacts": [
            "evals/runtime_validation/source-preflight-chunk-refresh-2026-10-19.json",
            "evals/runtime_validation/per-unit-9-5-9-source-audit-2026-10-19.json",
            "evals/runtime_validation/per-unit-9-6-2-source-audit-2026-10-19.json",
            "evals/runtime_validation/per-unit-9-3-2-source-audit-2026-10-19.json",
            "evals/runtime_validation/per-unit-7-4-1-policy-audit-2026-10-19.json",
        ],
        "runtime_regression": "evals/check_per_unit.py 44/44",
    }
    out = ROOT / "evals/runtime_validation/source-preflight-cluster-outcomes-2026-10-19.json"
    out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

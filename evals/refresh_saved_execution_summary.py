"""Reconcile index summary metadata from its saved status IDs (no recalculation)."""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT))
from evals.check_draft_executability import CALCULATORS
from backend.agent.rules.misfiled import misfiled_ids
from backend.agent.tools.calc.adjustments import classify_adjustment

INDEX = ROOT / "data/drafts/executable.json"
data = json.loads(INDEX.read_text(encoding="utf-8"))
packages = {}
for path in (ROOT / "data/drafts/specs").rglob("*.json"):
    package = json.loads(path.read_text(encoding="utf-8"))
    packages[package["draft"]["id"]] = package
excluded = misfiled_ids()
exec_ids = set(data["executable"])
failures = {item["id"]: item for item in data["failed"]}
skipped = {item["id"]: item for item in data["skipped"]}
assert not (exec_ids & set(failures) or exec_ids & set(skipped) or set(failures) & set(skipped))
assert exec_ids | set(failures) | set(skipped) == set(packages)
assert excluded <= set(skipped)

attempted = Counter()
passed = Counter()
scopes = defaultdict(Counter)
adjustments = Counter()
for ident, package in packages.items():
    if ident in excluded:
        continue
    draft = package["draft"]
    kind = package.get("calc_type")
    scope = "공통/6장" if draft["division"] == "공통" and draft["section_no"].startswith("6-") else "기타"
    scopes[scope]["total"] += 1
    if ident in exec_ids:
        if kind in CALCULATORS:
            attempted[kind] += 1
            passed[kind] += 1
            scopes[scope]["attempted"] += 1
        scopes[scope]["executable"] += 1
    elif ident in failures and failures[ident].get("stage") != "source_preflight" and kind in CALCULATORS:
        attempted[kind] += 1
        scopes[scope]["attempted"] += 1
    if ident in exec_ids or (ident in failures and failures[ident].get("stage") != "source_preflight"
                             and kind in CALCULATORS):
        params = draft.get("quantity_model", {}).get("params", {})
        for rule in params.get("surcharges", []) + params.get("note_adjustments", []):
            adjustments[classify_adjustment(draft, rule)] += 1

calculator_skips = sum(item.get("stage") == "calculator_selection" for item in skipped.values())
summary = data["summary"]
summary.update({
    "total": sum(item["total"] for item in scopes.values()),
    "inventory_total": len(packages),
    "executable": len(exec_ids),
    "failed": len(failures),
    "excluded_from_execution": len(excluded),
    "skipped_without_compatible_calculator": calculator_skips,
    "skipped_misfiled": len(excluded),
    "source_preflight_failures": sum(item.get("stage") == "source_preflight" for item in failures.values()),
    "by_calc_type": {kind: {"attempted": attempted[kind], "executable": passed[kind]} for kind in CALCULATORS},
    "failure_reasons_top10": Counter(item.get("reason", "") for item in failures.values()).most_common(10),
    "by_scope": {name: dict(values) for name, values in scopes.items()},
    "adjustment_items": dict(adjustments),
})
INDEX.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"executable": len(exec_ids), "failed": len(failures), "unsupported": calculator_skips,
                  "excluded": len(excluded), "by_calc_type": summary["by_calc_type"],
                  "failure_reasons_top10": summary["failure_reasons_top10"]}, ensure_ascii=False, indent=2))

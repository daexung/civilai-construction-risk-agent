"""Promote 6-1-1 after restoring and independently checking source dash cells."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID = "2026-정오표1차/기계설비/6-1-1/유량계(직독식)설치"
REASON = "unresolvable: p735-t0: 행 '65~80', 열 '보호통' — 열 후보 0개"
INDEX = ROOT / "data/drafts/executable.json"
AUDIT = ROOT / "evals/runtime_validation/per-unit-6-1-1-source-dashes-2026-10-19.json"
RECORD = ROOT / "evals/runtime_validation/executable-6-1-1-source-dash-promotion-2026-10-19.json"

audit = json.loads(AUDIT.read_text(encoding="utf8"))
assert audit["status"] == "source_sparse_cells_verified"
assert audit["source"]["unique_cells_checked"] == 28
assert audit["runtime"]["exact_size_item_routes"] == 14
assert audit["runtime"]["execution_preflight_combinations"] == 56
assert audit["runtime"]["execution_preflight_statuses"] == {"computed": 56, "blocked": 0}
idx = json.loads(INDEX.read_text(encoding="utf8"))
assert ID not in idx["executable"]
failed = [x for x in idx["failed"] if x.get("id") == ID]
assert len(failed) == 1 and failed[0].get("reason") == REASON, failed
idx["failed"] = [x for x in idx["failed"] if x.get("id") != ID]
idx["executable"] = sorted([*idx["executable"], ID])
summary = idx["summary"]
summary["executable"] = len(idx["executable"])
summary["failed"] = len(idx["failed"])
summary["by_calc_type"]["per_unit"]["executable"] += 1
summary["by_scope"]["기타"]["executable"] += 1
summary["failure_reasons_top10"] = [[r, n - 1 if r == REASON else n]
                                    for r, n in summary["failure_reasons_top10"] if r != REASON or n > 1]
INDEX.write_text(json.dumps(idx, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
record = {"id": ID, "previous_status": "failed", "current_status": "executable",
          "previous_failure_reason": REASON, "verification": str(AUDIT.relative_to(ROOT)),
          "scope": "28 original table cells including eight source dashes, 14 exact size/item paths and 56 preflight combinations; original p.679 visually checked.",
          "runtime_changes": [], "previously_passing_results_affected": 0,
          "current_counts": {"executable": len(idx["executable"]), "failed": len(idx["failed"]),
                             "unsupported": summary["skipped_without_compatible_calculator"],
                             "excluded": summary["excluded_from_execution"]},
          "full_rule_verification": False}
RECORD.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
print(json.dumps(record["current_counts"], ensure_ascii=True))

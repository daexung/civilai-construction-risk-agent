"""Promote 13-5-1 after independent source table and calculation checks."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID = "2026-정오표1차/기계설비/13-5-1/보일러설치"
INDEX = ROOT / "data/drafts/executable.json"
AUDIT = ROOT / "evals/runtime_validation/13-5-1-exact-source-routes-audit-2026-10-19.json"
RECORD = ROOT / "evals/runtime_validation/executable-13-5-1-exact-multi-table-promotion-2026-10-19.json"

def main():
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["status"] == "passed" and audit["numeric_source_cells_independently_compared"] == 49
    assert audit["source_rule_cells_independently_compared"] == 1
    assert audit["work_type_routes"] == 15 and audit["normal_capacity_output_lines"] == 43
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    assert ID not in index["executable"]
    old = [x for x in index["failed"] if x.get("id") == ID]
    assert len(old) == 1
    index["failed"] = [x for x in index["failed"] if x.get("id") != ID]
    reason = old[0]["reason"]
    for row in index["summary"]["failure_reasons_top10"]:
        if row[0] == reason:
            row[1] -= 1
            break
    index["summary"]["failure_reasons_top10"] = [x for x in index["summary"]["failure_reasons_top10"] if x[1] > 0]
    index["executable"] = sorted([*index["executable"], ID])
    index["summary"]["by_calc_type"]["per_unit"]["executable"] += 1
    index["summary"]["by_scope"]["기타"]["executable"] += 1
    index["summary"]["executable"] = len(index["executable"])
    index["summary"]["failed"] = len(index["failed"])
    INDEX.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    counts = {"executable": len(index["executable"]), "failed": len(index["failed"]),
              "unsupported": index["summary"]["skipped_without_compatible_calculator"],
              "excluded": index["summary"]["excluded_from_execution"]}
    RECORD.write_text(json.dumps({
        "id": ID, "previous_status": "failed", "current_status": "executable",
        "previous_reason": reason,
        "root_causes": ["The source row values were fragmented across p.826-p.827 and the selector treated the literal header work_type as a table identifier.", "The p.826 Chain block row had three values copied incorrectly; the printed source has 0.021, 0.028, 0.028, 0.028.", "The section uses six independent denominator units, and 50만㎾ reference rows are selected only for Tube Panel/Header tasks."],
        "verification": str(AUDIT.relative_to(ROOT)),
        "source_evidence": "Original PDF physical pp.826-827 (printed pp.770-771) visually reviewed; 49 numeric rate cells, one 10% rule cell, task row grids, units and special-capacity rows independently checked.",
        "runtime_changes": ["opt-in table-specific row value routing", "opt-in row-specific source labor numerator units"],
        "baseline_impact": "These routes are declared only by baseline-failed 13-5-1. Targeted source audits for 13-8-1, 13-7-20 and 13-8-5 and check_per_unit.py 44/44 passed after shared per_unit changes.",
        "full_rule_verification": False,
        "remaining_limits": ["Source note excludes 본용접 from direct unit-rate calculation; it remains explicitly uncalculated.", "Offline wage catalog can return PARTIAL for source trades without exact mappings.", "This audit does not claim inventory-wide or all-rule completion."],
        "focused_regressions": ["All 15 work types run through their exact source table and task-dependent unit; 43 output lines checked against independent rational calculations.", "49 numeric rates plus the inspection/calibration 10% source cell independently checked.", "High-capacity reference routes: 3 Tube Panel and 3 Header cells; unrelated high-capacity tasks still compute; Buckstay remains blocked only for its exact unresolved source condition.", "All 15 normal and two high-capacity routes passed offline pricing as PRICED or PARTIAL."],
        "counts_after_promotion": counts,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(counts, ensure_ascii=False))

if __name__ == "__main__":
    main()

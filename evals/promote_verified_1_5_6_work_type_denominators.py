"""Index the exact source-backed 1-5-6 repair without a broad replay."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC_ID = "2026-정오표1차/공통/1-5-6/공사용수"
INDEX = ROOT / "data/drafts/executable.json"
AUDIT = ROOT / "evals/runtime_validation/per-unit-1-5-6-work-type-denominators-2026-10-19.json"
RECORD = ROOT / "evals/runtime_validation/executable-1-5-6-work-type-denominators-promotion-2026-10-19.json"

def main() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["status"] == "source_rows_and_work_dependent_denominators_verified"
    assert audit["source"]["source_cells_checked"] == 10
    assert audit["runtime"]["computed_routes"] == 9 and audit["runtime"]["blocked_routes"] == 1
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    assert SPEC_ID not in index["executable"]
    failures = [x for x in index["failed"] if x.get("id") == SPEC_ID]
    assert len(failures) == 1 and failures[0].get("stage") == "calculator_execution_or_rule_gate", failures
    previous_reason = failures[0]["reason"]
    index["failed"] = [x for x in index["failed"] if x.get("id") != SPEC_ID]
    index["executable"] = sorted([*index["executable"], SPEC_ID])
    summary = index["summary"]
    summary["by_calc_type"]["per_unit"]["executable"] += 1
    summary["by_scope"]["기타"]["executable"] += 1
    updated = []
    for reason, count in summary["failure_reasons_top10"]:
        if reason == previous_reason:
            if count > 1:
                updated.append([reason, count - 1])
        else:
            updated.append([reason, count])
    summary["failure_reasons_top10"] = updated
    INDEX.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    record = {
        "id": SPEC_ID, "previous_status": "failed", "current_status": "executable",
        "previous_failure_reason": previous_reason,
        "verification": str(AUDIT.relative_to(ROOT)),
        "scope": "Printed p.33: all 10 source rows and denominator units checked; nine numeric work types compute and actual estimate flow asks the exact unit after work type.",
        "policy_open": "잡용수 remains blocked on its source-stated 40-50% range and unspecified base usage.",
        "runtime_changes": [], "previously_passing_results_affected": 0,
        "current_counts": {"executable": len(index["executable"]), "failed": len(index["failed"]),
                           "unsupported": summary["skipped_without_compatible_calculator"],
                           "excluded": summary["excluded_from_execution"]},
        "full_rule_verification": False,
    }
    RECORD.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record["current_counts"], ensure_ascii=False))

if __name__ == "__main__":
    main()

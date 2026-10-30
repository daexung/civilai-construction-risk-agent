"""Promote civil 8-1-3 after its focused source and execution audit."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC_ID = "2026-정오표1차/토목/8-1-3/천공(암반층)"
REASON = "기본 조합 unresolvable: p453-t2: 행 '직종', 열 'rock_type + ' ' + hole_size' — 열 후보 0개"
INDEX = ROOT / "data/drafts/executable.json"
AUDIT = ROOT / "evals/runtime_validation/per-unit-8-1-3-transposed-continuation-2026-10-19.json"
RECORD = ROOT / "evals/runtime_validation/executable-8-1-3-transposed-continuation-promotion-2026-10-19.json"


def main() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["status"] == "source_cells_and_continuation_axes_verified"
    assert audit["source"]["unique_source_cells_checked"] == 70
    assert audit["runtime"]["exact_rock_hole_routes"] == 10
    assert audit["runtime"]["preflight_combinations"] == 280
    assert set(audit["runtime"]["preflight_statuses"]) <= {"computed", "blocked"}
    assert audit["runtime"]["preflight_statuses"]["computed"] > 0
    result = json.loads(INDEX.read_text(encoding="utf-8"))
    assert SPEC_ID not in result["executable"]
    failures = [item for item in result["failed"] if item.get("id") == SPEC_ID]
    assert len(failures) == 1 and failures[0].get("reason") == REASON, failures
    result["failed"] = [item for item in result["failed"] if item.get("id") != SPEC_ID]
    result["executable"] = sorted([*result["executable"], SPEC_ID])
    summary = result["summary"]
    summary["executable"] = len(result["executable"])
    summary["failed"] = len(result["failed"])
    summary["by_calc_type"]["per_unit"]["executable"] += 1
    summary["by_scope"]["기타"]["executable"] += 1
    reasons = []
    for reason, count in summary["failure_reasons_top10"]:
        if reason == REASON:
            if count > 1:
                reasons.append([reason, count - 1])
        else:
            reasons.append([reason, count])
    summary["failure_reasons_top10"] = reasons
    INDEX.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    record = {
        "id": SPEC_ID, "previous_status": "failed", "current_status": "executable",
        "previous_failure_reason": REASON,
        "verification": str(AUDIT.relative_to(ROOT)),
        "scope": "70 unique original source cells, ten exact rock/hole routes, source dash exclusions, and 280 runner preflight combinations (80 computed, 200 source policy blocked).",
        "runtime_changes": ["per_unit.additional_unit_rates exact column selector and row_by_trade (opt-in)",
                            "daily_crew._axis_key exact_component_inputs (opt-in)"],
        "previously_passing_results_affected": 0,
        "focused_runtime_regressions": {
            "check_per_unit.py": "44/44",
            "6-3-3": "76 source cells; 38 routes (31 computed, 7 explicit dash blocks)",
            "8-1-2": "56 cells; 8/8 routes and preflight computed",
            "6-2-3": "21 cells; 7 source routes; 49 conditional cases blocked with citations",
        },
        "current_counts": {"executable": len(result["executable"]), "failed": len(result["failed"]),
                           "unsupported": summary["skipped_without_compatible_calculator"],
                           "excluded": summary["excluded_from_execution"]},
        "full_rule_verification": False,
    }
    RECORD.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False))


if __name__ == "__main__":
    main()

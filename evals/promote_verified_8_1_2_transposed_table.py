"""Apply the focused 8-1-2 source and runtime result to the saved index."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC_ID = "2026-정오표1차/토목/8-1-2/천공(토사, 자갈 및 호박돌층)"
REASON = "기본 조합 unresolvable: p453-t1: 행 '고정 행이름', 열 'soil_type + ' ' + hole_size' — 열 후보 0개"
INDEX = ROOT / "data/drafts/executable.json"
AUDIT = ROOT / "evals/runtime_validation/per-unit-8-1-2-transposed-merged-table-2026-10-19.json"
RECORD = ROOT / "evals/runtime_validation/executable-8-1-2-transposed-table-promotion-2026-10-19.json"


def main() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["status"] == "source_cells_and_transposed_axes_verified"
    assert audit["source"]["unique_source_cells_checked"] == 56
    assert audit["runtime"]["execution_preflight_combinations"] == 8
    assert audit["runtime"]["execution_preflight_statuses"] == {"computed": 8, "blocked": 0}
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
        "scope": "56 unique PDF cells and eight exact soil/hole routes, including six source-dash exclusions for chopping bits; all eight execution-preflight combinations computed.",
        "runtime_changes": ["per_unit.resource_kinds (opt-in)", "per_unit.row_by_trade (opt-in)"],
        "previously_passing_results_affected": 0,
        "current_counts": {"executable": len(result["executable"]),
                           "failed": len(result["failed"]),
                           "unsupported": summary["skipped_without_compatible_calculator"],
                           "excluded": summary["excluded_from_execution"]},
        "full_rule_verification": False,
    }
    RECORD.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record["current_counts"], ensure_ascii=False))


if __name__ == "__main__":
    main()

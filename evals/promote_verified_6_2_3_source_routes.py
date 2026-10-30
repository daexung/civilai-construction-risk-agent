"""Apply the focused 6-2-3 result to the saved execution index."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC_ID = "2026-정오표1차/공통/6-2-3/현장조립"
REASON = "기본 조합 unresolvable: p190-t0: 열 지정 없음 (후보 3개)"
INDEX = ROOT / "data/drafts/executable.json"
AUDIT = ROOT / "evals/runtime_validation/daily-crew-6-2-3-exact-source-routes-2026-10-19.json"
RECORD = ROOT / "evals/runtime_validation/executable-6-2-3-source-route-promotion-2026-10-19.json"


def main() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["status"] == "source_cell_and_targeted_runtime_verified"
    assert audit["source"]["independent_cells_checked"] == 21
    assert audit["runtime"]["combinations_checked"] == 56
    assert audit["runtime"]["special_condition_combinations_fail_closed"] == 49
    result = json.loads(INDEX.read_text(encoding="utf-8"))
    assert SPEC_ID not in result["executable"]
    failures = [item for item in result["failed"] if item.get("id") == SPEC_ID]
    assert len(failures) == 1 and failures[0].get("reason") == REASON, failures
    result["failed"] = [item for item in result["failed"] if item.get("id") != SPEC_ID]
    result["executable"] = sorted([*result["executable"], SPEC_ID])
    summary = result["summary"]
    summary["executable"] = len(result["executable"])
    summary["failed"] = len(result["failed"])
    summary["by_calc_type"]["daily_crew"]["executable"] += 1
    summary["by_scope"]["공통/6장"]["executable"] += 1
    updated_reasons = []
    for reason, count in summary["failure_reasons_top10"]:
        if reason == REASON:
            if count > 1:
                updated_reasons.append([reason, count - 1])
        else:
            updated_reasons.append([reason, count])
    summary["failure_reasons_top10"] = updated_reasons
    INDEX.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    record = {
        "id": SPEC_ID, "previous_status": "failed", "current_status": "executable",
        "previous_failure_reason": REASON,
        "verification": str(AUDIT.relative_to(ROOT)),
        "scope": "7 exact work-type routes and all 56 boolean-condition combinations; 49 source-uncertain special-condition combinations failed closed.",
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

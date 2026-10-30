"""Apply the focused 6-3-3 result to the saved execution index."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC_ID = "2026-정오표1차/토목/6-3-3/도장"
REASON = "unresolvable: p424-t0: 행 '800', 열 '' — 열 후보 2개"
INDEX = ROOT / "data/drafts/executable.json"
AUDIT = ROOT / "evals/runtime_validation/per-unit-6-3-3-exact-coating-axes-2026-10-19.json"
RECORD = ROOT / "evals/runtime_validation/executable-6-3-3-exact-axis-promotion-2026-10-19.json"


def main() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["status"] == "source_cell_and_exact_axis_verified"
    assert audit["source"]["independent_cells_checked"] == 76
    assert audit["runtime"]["routes_checked"] == 38
    assert audit["runtime"]["execution_preflight_combinations"] == 38
    assert audit["runtime"]["execution_preflight_statuses"] == {"computed": 31, "blocked": 7}
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
        "scope": "All 76 rate/dash cells on original PDF p.424, 38 exact diameter/coating routes, and 31 computed plus seven source-dash-blocked combinations.",
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

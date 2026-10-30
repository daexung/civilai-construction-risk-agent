"""Index exact work-dependent unit routes for mechanical 10-8-1."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC_ID = "2026-정오표1차/기계설비/10-8-1/소화약제_소화설비설치"
INDEX = ROOT / "data/drafts/executable.json"
AUDIT = ROOT / "evals/runtime_validation/per-unit-10-8-1-mixed-item-units-2026-10-19.json"
RECORD = ROOT / "evals/runtime_validation/executable-10-8-1-mixed-item-units-promotion-2026-10-19.json"


def main() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["status"] == "all_mixed_item_units_and_source_rates_verified"
    assert audit["source"]["source_rows_checked"] == 27
    assert audit["source"]["unit_and_labor_cells_checked"] == 54
    assert audit["runtime"]["computed_routes"] == 27
    assert set(audit["runtime"]["estimate_flows_by_unit"]) == {"개", "조", "면"}
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    assert SPEC_ID not in index["executable"]
    failures = [item for item in index["failed"] if item.get("id") == SPEC_ID]
    assert len(failures) == 1 and failures[0].get("stage") == "calculator_execution_or_rule_gate", failures
    previous_reason = failures[0]["reason"]
    index["failed"] = [item for item in index["failed"] if item.get("id") != SPEC_ID]
    index["executable"] = sorted([*index["executable"], SPEC_ID])
    summary = index["summary"]
    summary["by_calc_type"]["per_unit"]["executable"] += 1
    summary["by_scope"]["기타"]["executable"] += 1
    summary["executable"] = len(index["executable"])
    summary["failed"] = len(index["failed"])
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
        "previous_failure_reason": previous_reason, "verification": str(AUDIT.relative_to(ROOT)),
        "scope": "Printed p.711: 27 exact item rows, each denominator and rate checked against original source; 27 routes and live estimate quantity questions for 개, 조 and 면 passed.",
        "runtime_changes": ["per_unit opt-in basis_by_selected_unit uses the exact source-mapped denominator for a mixed-denominator table",
                            "per-unit source citation row_map points canonical item selections to exact source row labels",
                            "estimate parser recognizes the source unit 조"],
        "previously_passing_results_affected": 0,
        "policy_open": "Source note ③ requires extinguisher-agent/container installation to be accounted separately; this route covers the listed equipment installation rates only.",
        "current_counts": {"executable": len(index["executable"]), "failed": len(index["failed"]),
                           "unsupported": summary["skipped_without_compatible_calculator"],
                           "excluded": summary["excluded_from_execution"]},
        "full_rule_verification": False,
    }
    RECORD.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record["current_counts"], ensure_ascii=False))


if __name__ == "__main__":
    main()

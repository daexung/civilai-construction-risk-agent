"""Index the source-verified task-dependent units for mechanical 12-1-1."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC_ID = "2026-정오표1차/기계설비/12-1-1/계기반설치"
INDEX = ROOT / "data/drafts/executable.json"
AUDIT = ROOT / "evals/runtime_validation/per-unit-12-1-1-panel-item-units-2026-10-19.json"
RECORD = ROOT / "evals/runtime_validation/executable-12-1-1-panel-item-units-promotion-2026-10-19.json"


def main() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["status"] == "source_cells_and_all_task_dependent_units_verified"
    assert audit["source"]["source_rows_checked"] == 14
    assert audit["source"]["labor_rate_cells_checked"] == 28
    assert audit["runtime"]["routes_computed"] == 14
    assert audit["runtime"]["estimate_flow"]["status"] == "ok"
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
        "scope": "Printed p.717: 14 rows, 28 rates, and 14 exact item-dependent units checked; actual estimate flow asks 면 after selecting a panel row and computes the exact labor lines.",
        "policy_open": "This audit covers the base finished-panel route only; rear-panel, unfinished-panel, and instrument-test adjustments are not claimed verified.",
        "runtime_changes": ["per-unit quantity fields tolerate a null base unit when a source-declared unit_by map provides the exact selected unit",
                            "estimate quantity parser recognizes 면 as a standalone quantity unit"],
        "previously_passing_results_affected": 0,
        "current_counts": {"executable": len(index["executable"]), "failed": len(index["failed"]),
                           "unsupported": summary["skipped_without_compatible_calculator"],
                           "excluded": summary["excluded_from_execution"]},
        "full_rule_verification": False,
    }
    RECORD.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record["current_counts"], ensure_ascii=False))


if __name__ == "__main__":
    main()

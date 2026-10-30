"""Promote 13-3-1 after full explicit table routes and policy gates pass."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID = "2026-정오표1차/기계설비/13-3-1/pipe보온"
INDEX = ROOT / "data/drafts/executable.json"
AUDIT = ROOT / "evals/runtime_validation/per-unit-13-3-1-insulation-tables-2026-10-19.json"
RECORD = ROOT / "evals/runtime_validation/executable-13-3-1-insulation-tables-promotion-2026-10-19.json"


def main() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["status"] == "source_matrices_units_surcharges_and_materials_verified"
    assert audit["source"]["cells_checked"] == 1020
    assert audit["runtime"]["unit_rate_routes"] == 2040
    assert audit["runtime"]["additional_material_routes"] == 1020
    assert all(flow["status"] == "ok" for flow in audit["runtime"]["live_estimate_flows"])
    assert len(audit["runtime"]["blocked_source_policies"]) == 3
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    assert ID not in index["executable"]
    failures = [entry for entry in index["failed"] if entry.get("id") == ID]
    assert len(failures) == 1 and failures[0].get("stage") == "calculator_execution_or_rule_gate"
    previous_reason = failures[0]["reason"]
    index["failed"] = [entry for entry in index["failed"] if entry.get("id") != ID]
    index["executable"] = sorted([*index["executable"], ID])
    summary = index["summary"]
    summary["by_calc_type"]["per_unit"]["executable"] += 1
    summary["by_scope"]["기타"]["executable"] += 1
    summary["executable"] = len(index["executable"])
    summary["failed"] = len(index["failed"])
    reasons = []
    for reason, count in summary["failure_reasons_top10"]:
        if reason == previous_reason:
            if count > 1:
                reasons.append([reason, count - 1])
        else:
            reasons.append([reason, count])
    summary["failure_reasons_top10"] = reasons
    INDEX.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    counts = {"executable": len(index["executable"]), "failed": len(index["failed"]),
              "unsupported": summary["skipped_without_compatible_calculator"],
              "excluded": summary["excluded_from_execution"]}
    record = {
        "id": ID, "previous_status": "failed", "current_status": "executable",
        "previous_failure_reason": previous_reason,
        "verification": str(AUDIT.relative_to(ROOT)),
        "source_recovery": "Five 30–90 mm source tables were independently reconstructed from physical PDF pages 813–817 (printed pp.757–761), 1,020 rate/material cells checked; exact first-size symbol route preserved.",
        "runtime_changes": ["per_unit additional_materials exact row_selector and explicit quantity_unit support",
                            "fill parses quantity using a selected unit_by choice",
                            "compose reports the resolved quantity unit"],
        "previously_passing_results_affected": 1,
        "previously_passing_results_reverified": ["2026-정오표1차/토목/1-9-3/낙석방지책설치 via evals/check_work_dependent_quantity_unit.py"],
        "policy_open": "91 mm+ formula, Cold qualitative surcharge and multi-layer note combination remain cited and blocked. 50% Prefabricated Sheet / 100% raw-material labor multipliers cite the printed note.",
        "current_counts": counts, "full_rule_verification": False,
    }
    RECORD.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(counts, ensure_ascii=False))


if __name__ == "__main__":
    main()

"""Record Roller Table mixed-quantity calculation after source and price checks."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID = "2026-정오표1차/기계설비/13-7-20/Roller Table 조립설치"
INDEX = ROOT / "data/drafts/executable.json"
AUDIT = ROOT / "evals/runtime_validation/13-7-20-mixed-quantity-source-calc-audit-2026-10-19.json"
RECORD = ROOT / "evals/runtime_validation/executable-13-7-20-multi-quantity-promotion-2026-10-19.json"


def main():
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["status"] == "passed"
    assert audit["numeric_cells"] == 7 and audit["task_rate_lines"] == 7
    assert audit["equipment_type_routes"] == 10 and audit["source_exclusion_notes"] == 4
    assert audit["expected_total_person_days"] == "68823/5000"
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    assert ID not in index["executable"]
    old = [item for item in index["failed"] if item.get("id") == ID]
    assert len(old) == 1
    index["failed"] = [item for item in index["failed"] if item.get("id") != ID]
    reason = old[0]["reason"]
    for item in index["summary"]["failure_reasons_top10"]:
        if item[0] == reason:
            assert item[1] > 0
            item[1] -= 1
            break
    index["summary"]["failure_reasons_top10"] = [
        [key, count] for key, count in index["summary"]["failure_reasons_top10"] if count > 0]
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
        "root_cause": "The source rows use independent quantity bases (day, square meter, and ton) and the spec omitted technical-management days while binding all rates to the ton input. The p.832 table now maps each exact row and basis to its own declared quantity. The source 10% inspection/calibration note is implemented as a fixed, cited multiplier over all labor lines except technician management. The selected row's exact labor columns are declared; no trade is inferred from fuzzy matching.",
        "verification": str(AUDIT.relative_to(ROOT)),
        "source_evidence": "Original PDF physical p.888/printed p.832 visually checked for seven numeric labor cells and the 10% source cell; continuation p.889/printed p.833 checked for four cited exclusions and equipment note.",
        "runtime_changes": ["per_unit opt-in trades_by_row exact row-resource declaration (introduced for failed-at-baseline 13-8-1)",
                            "per_unit opt-in add_source_percent with source citation and exact excluded trade filter"],
        "baseline_impact": "Both opt-in branches are declared only by items failed in the saved 692 executable baseline. The source-percent branch passed 13-7-20 direct route/price audit and check_per_unit.py 44/44.",
        "full_rule_verification": False,
        "remaining_limits": ["Offline price remains PARTIAL because the wage catalog has no exact mapping for source trade 기계기사; no wage alias was invented.",
                             "Packaging/small transport, foundation chipping/marking/centering, electrical wiring and on-site fabrication remain separately excluded per cited notes."],
        "focused_regressions": ["p.832: seven rate cells and the source 10% rule; 10 equipment types, seven exact rate lines and four p.833 exclusions.",
                                "Independent quantity calculation: 13.7646 person-days at 4 management days, 3㎡ surface prep and 2 tons.",
                                "Offline 2026H2 price: all mapped wage lines priced; 기계기사 remains the sole missing mapping.",
                                "check_per_unit.py 44/44"],
        "counts_after_promotion": counts,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(counts, ensure_ascii=False))


if __name__ == "__main__":
    main()

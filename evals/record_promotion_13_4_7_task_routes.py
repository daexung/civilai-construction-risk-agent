"""Record tank cleaning after exact task, note-rule and price-route checks."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID = "2026-정오표1차/기계설비/13-4-7/탱크청소"
INDEX = ROOT / "data/drafts/executable.json"
AUDIT = ROOT / "evals/runtime_validation/13-4-7-task-routes-source-calc-audit-2026-10-19.json"
RECORD = ROOT / "evals/runtime_validation/executable-13-4-7-task-routes-promotion-2026-10-19.json"


def main() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["status"] == "all_numeric_source_cells_task_routes_and_secondary_area_price_verified"
    assert audit["source"]["numeric_cells"] == 16 and audit["runtime"]["source_cell_route_cases"] == 18
    assert audit["runtime"]["clean_out_door_cases"] == 2
    assert not audit["runtime"]["full_rules_verified"]
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
        "root_cause": "The source table is task-row × fluid-column, but the spec treated the row as a literal selector and tried one rate for all tasks. Each selected task now routes to its exact row. The 20% clean-out-door adjustment applies only to scoop/dirt rows; 80% extra rust work uses its own source-backed area input.",
        "verification": str(AUDIT.relative_to(ROOT)),
        "runtime_changes": ["per_unit additional_unit_rates source multiplier and separate quantity input routing",
                            "price_unit absolute secondary-quantity line totals"],
        "baseline_impact": "10-1-1 wood windows is the one cached 692 executable that declares a secondary additional_unit_rates input. Focused direct calculator and offline price checks were rerun: 5m × 0.010 person-day/m = 0.05 person-day. Other baseline additional rates use the primary input.",
        "full_rule_verification": False,
        "remaining_limits": ["Toxic-gas adjustment stays blocked because the source provides no rate.",
                             "Water cells for pour-back and drum transport are source dashes and are rejected.",
                             "Consumables are separately accounted; material pricing remains partial."],
        "focused_regressions": ["check_per_unit.py 44/44", "check_cost_statement.py 8/8",
                                "13-4-7 source/calc audit: 16 numeric cells, 18 routes and offline price",
                                "10-1-1 secondary quantity direct price check"],
        "counts_after_promotion": counts,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(counts, ensure_ascii=False))


if __name__ == "__main__":
    main()

"""Index the source-verified 8-3-6 route without replaying the inventory."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC_ID = "2026-정오표1차/기계설비/8-3-6/방열기설치"
INDEX = ROOT / "data/drafts/executable.json"
AUDIT = ROOT / "evals/runtime_validation/per-unit-8-3-6-radiator-rows-2026-10-19.json"
RECORD = ROOT / "evals/runtime_validation/executable-8-3-6-radiator-promotion-2026-10-19.json"

def main() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["status"] == "source_cells_and_supported_routes_verified"
    assert audit["source"]["unique_rate_cells_checked"] == 22
    assert audit["runtime"]["computed_routes"] == 11
    assert audit["runtime"]["estimate_flow"]["status"] == "ok"
    path = ROOT / "data/drafts/specs/기계설비/8-3-6.json"
    package = json.loads(path.read_text(encoding="utf-8"))
    assert package["draft"]["id"] == SPEC_ID and package["calc_type"] == "per_unit"

    index_path = ROOT / "data/drafts/executable.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert SPEC_ID not in index["executable"]
    matches = [entry for entry in index["skipped"] if entry.get("id") == SPEC_ID]
    assert len(matches) == 1 and matches[0].get("stage") == "calculator_selection", matches
    index["skipped"] = [entry for entry in index["skipped"] if entry.get("id") != SPEC_ID]
    index["executable"] = sorted([*index["executable"], SPEC_ID])
    summary = index["summary"]
    summary["skipped_without_compatible_calculator"] -= 1
    summary["by_calc_type"]["per_unit"]["attempted"] += 1
    summary["by_calc_type"]["per_unit"]["executable"] += 1
    summary["by_scope"]["기타"]["attempted"] += 1
    summary["by_scope"]["기타"]["executable"] += 1
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    record = {
        "id": SPEC_ID, "previous_status": "unsupported", "current_status": "executable",
        "verification": str(AUDIT.relative_to(ROOT)),
        "scope": "Original printed p.698 table: 11 specification rows and 22 labor cells; 11 supported routes; actual estimate flow asks the unit after radiator type and calculates 1m길트 in 1본 units.",
        "policy_open": "Panel radiator stays blocked because source does not select the convector length band.",
        "runtime_changes": ["per_unit.input_rate_adjustments.add_percent_per_count (opt-in)"],
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

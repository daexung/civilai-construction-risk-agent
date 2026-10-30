"""Index the source-verified task-unit and dash routes for mechanical 10-7-2."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC_ID = "2026-정오표1차/기계설비/10-7-2/스프링클러_전기설비설치"
INDEX = ROOT / "data/drafts/executable.json"
AUDIT = ROOT / "evals/runtime_validation/per-unit-10-7-2-task-units-and-dashes-2026-10-19.json"
RECORD = ROOT / "evals/runtime_validation/executable-10-7-2-task-units-and-dashes-promotion-2026-10-19.json"


def main() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["status"] == "source_units_and_explicit_dashes_verified"
    assert audit["source"]["cells_checked"] == 12
    assert audit["runtime"]["routes_computed"] == 4
    assert audit["runtime"]["helper_routes_excluded_by_source_dash"] == 4
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
        "scope": "Printed p.710: four exact item rows, four physical quantity-unit cells, four pipefitter rates, and four helper dashes; four routes calculate and source-dash helper exclusions are preserved.",
        "source_extraction_repair": "Restored the four visible 보통인부 dashes omitted from p766-t3 extraction text.",
        "policy_open": "The unrelated ancillary piping/insulation tasks stated in source note ③ remain separate and outside this calculation.",
        "runtime_changes": ["shared task-dependent quantity unit path through input unit_by and per-unit quantity_unit_selector",
                            "estimate quantity parser recognizes 면; focused regression verified"],
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

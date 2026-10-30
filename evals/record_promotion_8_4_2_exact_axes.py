"""Record 8-4-2 after exact axis and activity route checks."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID = "2026-정오표1차/토목/8-4-2/천공(암반층)"
INDEX = ROOT / "data/drafts/executable.json"
AUDIT = ROOT / "evals/runtime_validation/8-4-2-strata-activity-source-calc-audit-2026-10-19.json"
RECORD = ROOT / "evals/runtime_validation/executable-8-4-2-exact-axes-promotion-2026-10-19.json"


def main() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["status"] == "original_page_sample_cells_and_all_activity_routes_verified"
    assert audit["source"]["primary_sample_cells"] == 20
    assert audit["source"]["activity_cells"] == 20
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
        [reason, count] for reason, count in index["summary"]["failure_reasons_top10"] if count > 0]
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
        "root_cause": "The four source matrices have resource rows and composite rock-type × diameter columns. The spec incorrectly selected rock_type as row; connected rock-type table routes, resource rows, exact composite columns, and four separate activity rows.",
        "verification": str(AUDIT.relative_to(ROOT)),
        "runtime_changes": [],
        "source_scope": "Saved original images p459-p460 checked for 20 representative primary matrix cells and all 20 additional labor cells. Eight calculator cases cover all four strata tables and all four activity rows.",
        "full_rule_verification": False,
        "remaining_limits": ["Not every cell in four primary matrices independently matched to source images.",
                             "Material and equipment price coverage is incomplete."],
        "counts_after_promotion": counts,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(counts, ensure_ascii=False))


if __name__ == "__main__":
    main()

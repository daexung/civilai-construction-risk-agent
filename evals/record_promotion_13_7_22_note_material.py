"""Record the source-verified note-based material coefficient route."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID = "2026-정오표1차/기계설비/13-7-22/노기밀시험"
INDEX = ROOT / "data/drafts/executable.json"
AUDIT = ROOT / "evals/runtime_validation/13-7-22-note-material-source-calc-audit-2026-10-19.json"
RECORD = ROOT / "evals/runtime_validation/executable-13-7-22-note-material-promotion-2026-10-19.json"


def main() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["status"] == "source_labor_and_note_material_quantity_verified"
    assert audit["source"]["source_quote_checked"]
    assert audit["runtime"]["soap_quantity_at_100m3"] == "4 kg"
    assert not audit["runtime"]["full_rules_verified"]
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    assert ID not in index["executable"]
    failures = [item for item in index["failed"] if item.get("id") == ID]
    assert len(failures) == 1
    reason = failures[0]["reason"]
    index["failed"] = [item for item in index["failed"] if item.get("id") != ID]
    for key, count in index["summary"]["failure_reasons_top10"]:
        if key == reason:
            assert count > 0
            break
    else:
        raise AssertionError("failure reason missing from summary")
    index["summary"]["failure_reasons_top10"] = [
        [key, count - 1 if key == reason else count]
        for key, count in index["summary"]["failure_reasons_top10"]
        if count > 1 or key != reason
    ]
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
        "verification": str(AUDIT.relative_to(ROOT)),
        "root_cause": "per_unit accepted table-backed materials only; this source gives an explicit cited note coefficient. Added an opt-in source_rate route that requires a text citation and explicit dimensional basis.",
        "source_scope": "PDF physical p.890 / printed p.834: both labor cells and the exact 0.04 kg/m³ soap note independently checked.",
        "runtime_regression": "check_per_unit.py 44/44",
        "full_rule_verification": False,
        "partial_reason": "soap quantity calculates (4 kg per 100 m³); no soap unit price source and mechanical engineer wage mapping is missing.",
        "counts_after_promotion": counts,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(counts, ensure_ascii=False))


if __name__ == "__main__":
    main()

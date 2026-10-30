"""Promote 13-6-13 after checking all source rate cells and the 7% rule."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID = "2026-정오표1차/기계설비/13-6-13/Tainter_Gate_Guide_Metal_제작"
INDEX = ROOT / "data/drafts/executable.json"
AUDIT = ROOT / "evals/runtime_validation/13-6-13-source-rates-and-7-percent-audit-2026-10-19.json"
RECORD = ROOT / "evals/runtime_validation/executable-13-6-13-process-rates-promotion-2026-10-19.json"

def main():
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["status"] == "passed" and audit["numeric_source_cells_independently_compared"] == 21
    assert audit["source_percent_rule_cells_independently_compared"] == 1
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    assert ID not in index["executable"]
    old = [x for x in index["failed"] if x.get("id") == ID]
    assert len(old) == 1
    index["failed"] = [x for x in index["failed"] if x.get("id") != ID]
    reason = old[0]["reason"]
    for row in index["summary"]["failure_reasons_top10"]:
        if row[0] == reason:
            row[1] -= 1
            break
    index["summary"]["failure_reasons_top10"] = [x for x in index["summary"]["failure_reasons_top10"] if x[1] > 0]
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
        "root_cause": "The table contained 20 process rows and 21 exact rate cells, but the spec used literal non-input row/column selectors. The 'inspection' row states a 7% labor allowance rather than a numeric rate.",
        "verification": str(AUDIT.relative_to(ROOT)),
        "source_evidence": "Original PDF physical p.873/printed p.817 visually checked; 21 numeric source cells and the blank-valued '인력품의 7%' rule cell independently compared.",
        "runtime_changes": ["source row + trade cell routing using exact additional_unit_rates", "cited add_source_percent applied to the complete selected labor sum"],
        "baseline_impact": "Features are used by this baseline-failed case; shared default paths passed check_per_unit.py 44/44 after the runtime changes.",
        "full_rule_verification": False,
        "remaining_limits": ["Offline pricing is partial where the local wage catalog lacks exact trade mappings.", "This section audit is focused and is not an inventory-wide full-rule verification."],
        "focused_regressions": ["21 numeric rate cells over 20 source rows, all exact row/occupation/value citations checked.", "Source 7% rule cited and independently applied once to all 21 labor lines.", "Independent exact sum for two tons: 77147/625 person-days.", "Offline price path returned PARTIAL without external calls."],
        "counts_after_promotion": counts,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(counts, ensure_ascii=False))

if __name__ == "__main__":
    main()

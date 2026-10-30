"""Promote Trash Rack after restoring all labor and material cells."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID = "2026-정오표1차/기계설비/13-6-16/Trash_Rack_설치"
INDEX = ROOT / "data/drafts/executable.json"
AUDIT = ROOT / "evals/runtime_validation/13-6-16-exact-labor-material-source-audit-2026-10-19.json"
RECORD = ROOT / "evals/runtime_validation/executable-13-6-16-labor-material-promotion-2026-10-19.json"

def main():
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["status"] == "passed"
    assert audit["labor_source_cells_independently_compared"] == 41
    assert audit["material_source_cells_independently_compared"] == 5
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
        "root_cause": "OCR flattening combined 20 labor process rows across two pages into two composite rows, losing repeated trade cells; the material table also stored several process headings as one composite row.",
        "verification": str(AUDIT.relative_to(ROOT)),
        "source_evidence": "Original physical pp.876-877/printed pp.820-821 visually checked. Reconstructed and independently compared all 41 labor cells, all five material cells, and the oxygen cylinder note.",
        "runtime_changes": ["exact source rows and trade cells routed through primary and additional unit rates", "per-material note citation is appended to its exact source cell citation"],
        "baseline_impact": "New material citation branch and additional routes are declared only by this baseline-failed case; check_per_unit.py 44/44 rerun after shared changes.",
        "full_rule_verification": False,
        "remaining_limits": ["Offline pricing is partial for missing wage/material prices; source consumption quantities remain available and cited.", "This focused section audit is not an inventory-wide full-rule verification."],
        "focused_regressions": ["20 labor source rows, 41 rates; independent total 19.667 person-days/ton and 39.334 for two tons.", "Three material process rows, five source cells; 0.029 bottle oxygen, 0.012 bottle acetylene, 5.95 kg welding rods, 7.06 L tar epoxy, and 1.58 L thinner per ton.", "Oxygen cylinder quote cited on both gas material outputs.", "Offline price result PARTIAL without external calls."],
        "counts_after_promotion": counts,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(counts, ensure_ascii=False))

if __name__ == "__main__":
    main()

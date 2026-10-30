"""Record 13-8-5 after exact source-cell, quantity and offline price audit."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID = "2026-정오표1차/기계설비/13-8-5/탈질설비설치"
INDEX = ROOT / "data/drafts/executable.json"
AUDIT = ROOT / "evals/runtime_validation/13-8-5-mixed-quantity-source-calc-audit-2026-10-19.json"
RECORD = ROOT / "evals/runtime_validation/executable-13-8-5-mixed-quantity-promotion-2026-10-19.json"

def main():
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["status"] == "passed" and audit["numeric_source_cells"] == 28
    assert audit["exact_quantity_row_routes"] == 14 and audit["priced_unit_lines"] == 28
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
        "root_cause": "The source process rows span day, cubic-meter, square-meter, and ton bases across two tables; the previous model bound all work to one denominator and could not express the source 10% inspection rule. Each exact source row now has its own quantity route, resource unit, and table citation.",
        "verification": str(AUDIT.relative_to(ROOT)),
        "source_evidence": "Original physical pages 895/896 (printed 839/840) visually checked; 28 numeric labor cells and the source-percent cell independently compared against the extracted source rows.",
        "runtime_changes": ["opt-in additional_unit_rates per-trade basis/resource-unit/column routing", "source-percent adjustment filters explicit quantity inputs"],
        "baseline_impact": "Opt-in routes are used by failed-at-baseline specs only; check_per_unit.py 44/44 and focused 13-7-20, 13-8-1 source audits rerun after shared runtime changes.",
        "full_rule_verification": False,
        "remaining_limits": ["Offline price is partial because exact wage mappings are absent for 기계기사, 목공 and 건설기계운전조; no aliases inferred.", "Driver-crew composition/site-condition changes and equipment selection/cost remain explicitly uncalculated per source notes."],
        "focused_regressions": ["Independent source-cell mapping: 28 numeric cells plus one cited 10% rule cell.", "Fourteen exact work-row/resource routes across two tables; 28 lines and per-unit outputs checked against independent fractions.", "Offline price path: 23 mapped lines; five exact wage lines remain unpriced.", "check_per_unit.py 44/44; 13-7-20 targeted source/price audit passed."],
        "counts_after_promotion": counts,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(counts, ensure_ascii=False))

if __name__ == "__main__":
    main()

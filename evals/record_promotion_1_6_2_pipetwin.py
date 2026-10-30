"""Record the source-recovered PB twin-pipe section after focused validation."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID = "2026-정오표1차/기계설비/1-6-2/폴리부틸렌이중관접합및배관"
INDEX = ROOT / "data/drafts/executable.json"
AUDIT = ROOT / "evals/runtime_validation/1-6-2-pipetwin-source-calc-audit-2026-10-19.json"
RECORD = ROOT / "evals/runtime_validation/executable-1-6-2-pipetwin-promotion-2026-10-19.json"


def main() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["status"] == "independent_source_cells_and_calculation_verified"
    assert audit["source"]["distinct_cells"] == 4 and audit["runtime"]["full_rules_verified"]
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    assert ID not in index["executable"]
    old = [entry for entry in index["skipped"] if entry.get("id") == ID]
    assert len(old) == 1 and old[0]["stage"] == "calculator_selection"
    index["skipped"] = [entry for entry in index["skipped"] if entry.get("id") != ID]
    index["executable"] = sorted([*index["executable"], ID])
    index["summary"]["skipped_without_compatible_calculator"] -= 1
    index["summary"]["by_calc_type"]["per_unit"]["attempted"] += 1
    index["summary"]["by_calc_type"]["per_unit"]["executable"] += 1
    index["summary"]["by_scope"]["기타"]["attempted"] += 1
    index["summary"]["by_scope"]["기타"]["executable"] += 1
    index["summary"]["executable"] = len(index["executable"])
    index["summary"]["failed"] = len(index["failed"])
    INDEX.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    counts = {"executable": len(index["executable"]), "failed": len(index["failed"]),
              "unsupported": index["summary"]["skipped_without_compatible_calculator"],
              "excluded": index["summary"]["excluded_from_execution"]}
    RECORD.write_text(json.dumps({
        "id": ID, "previous_status": "unsupported", "current_status": "executable",
        "previous_reason": old[0]["reason"], "verification": str(AUDIT.relative_to(ROOT)),
        "source_recovery": "p713-t0 had lost both trade labels, the ø20 mm column and three rates. Recovered the explicit two-trade × two-diameter matrix from original PDF physical p.713 (printed p.657); repaired only this source chunk after original-page assertions.",
        "shared_runtime_changes": [], "full_rule_verification": True,
        "counts_after_promotion": counts,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(counts, ensure_ascii=False))


if __name__ == "__main__":
    main()

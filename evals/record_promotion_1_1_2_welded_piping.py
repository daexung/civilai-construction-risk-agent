"""Record the verified 1-1-2 transition from unsupported to executable."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID = "2026-정오표1차/기계설비/1-1-2/용접배관"
INDEX = ROOT / "data/drafts/executable.json"
AUDIT = ROOT / "evals/runtime_validation/1-1-2-welded-piping-source-calc-audit-2026-10-19.json"
RECORD = ROOT / "evals/runtime_validation/executable-1-1-2-welded-piping-promotion-2026-10-19.json"


def main() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["status"] == "source_rules_calculation_and_offline_price_verified"
    assert audit["source"]["base_cells"] == 16
    assert audit["runtime"]["cases"] == 5 and audit["runtime"]["offline_price_cases"] == 2
    assert audit["runtime"]["full_rules_verified"] is False
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    assert ID not in index["executable"]
    old = [entry for entry in index["skipped"] if entry.get("id") == ID]
    assert len(old) == 1 and old[0]["stage"] == "calculator_selection"
    index["skipped"] = [entry for entry in index["skipped"] if entry.get("id") != ID]
    index["executable"] = sorted([*index["executable"], ID])
    index["summary"]["skipped_without_compatible_calculator"] -= 1
    index["summary"]["by_calc_type"]["daily_crew"]["attempted"] += 1
    index["summary"]["by_calc_type"]["daily_crew"]["executable"] += 1
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
        "source_recovery": "Reconstructed all 16 pipe-size crew/output rows from original physical PDF p.701 (printed p.645); the restored p701-t1 source table was independently compared cell by cell.",
        "rule_verification": "Location changes -17/-23/+11%, lift adds 26% output, equipment rates 2% without lift / 10% with lift; five independent calculation cases and two offline prices passed.",
        "full_rule_verification": False, "counts_after_promotion": counts,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(counts, ensure_ascii=False))


if __name__ == "__main__":
    main()

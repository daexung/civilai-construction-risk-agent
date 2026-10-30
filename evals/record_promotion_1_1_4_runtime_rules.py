"""Record 1-1-4 after source-cell, rule-matrix, and offline-cost checks."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID = "2026-정오표1차/기계설비/1-1-4/그루브조인트식접합및배관"
INDEX = ROOT / "data/drafts/executable.json"
AUDIT = ROOT / "evals/runtime_validation/1-1-4-source-calc-audit-2026-10-19.json"
RECORD = ROOT / "evals/runtime_validation/executable-1-1-4-runtime-rules-promotion-2026-10-19.json"


def main() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["status"] == "source_rules_matrix_and_offline_price_verified"
    assert audit["source"]["base_rows"] == 18 and audit["runtime"]["cases"] == 144
    assert audit["runtime"]["offline_price_cases"] == 2 and audit["runtime"]["full_rules_verified"]
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    assert ID not in index["executable"]
    failures = [item for item in index["failed"] if item.get("id") == ID]
    assert len(failures) == 1 and failures[0]["reason"] == "KeyError: 'blocked'"
    index["failed"] = [item for item in index["failed"] if item.get("id") != ID]
    index["executable"] = sorted([*index["executable"], ID])
    for reason, count in index["summary"]["failure_reasons_top10"]:
        if reason == failures[0]["reason"]:
            assert count == 1
            break
    else:
        raise AssertionError("promotion failure reason missing from summary")
    index["summary"]["failure_reasons_top10"] = [
        [reason, count - 1 if reason == failures[0]["reason"] else count]
        for reason, count in index["summary"]["failure_reasons_top10"] if count > 1 or reason != failures[0]["reason"]]
    index["summary"]["by_calc_type"]["daily_crew"]["executable"] += 1
    index["summary"]["by_scope"]["기타"]["executable"] += 1
    index["summary"]["executable"] = len(index["executable"])
    index["summary"]["failed"] = len(index["failed"])
    INDEX.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    counts = {"executable": len(index["executable"]), "failed": len(index["failed"]),
              "unsupported": index["summary"]["skipped_without_compatible_calculator"],
              "excluded": index["summary"]["excluded_from_execution"]}
    RECORD.write_text(json.dumps({
        "id": ID, "previous_status": "failed", "current_status": "executable",
        "previous_reason": failures[0]["reason"], "verification": str(AUDIT.relative_to(ROOT)),
        "root_cause": "The section spec omitted empty blocked/crew_rules lists and did not map named source columns for crew counts. After these declarations were restored, the baseline run exposed an incorrect wage code (1016); p.647 maps 배관공 to the local source wage key 1039.",
        "source_reconstruction": "Original physical PDF p.703 / printed p.647: all 18 pipe sizes, two crew counts, three location rates and lift note independently checked.",
        "runtime_changes": [], "full_calculation_rules_verified": True,
        "partial_offline_quote": "Equipment rates compute correctly for both conditions. Overall price response remains PARTIAL because the source explicitly excludes four separately accounted items.",
        "counts_after_promotion": counts,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(counts, ensure_ascii=False))


if __name__ == "__main__":
    main()

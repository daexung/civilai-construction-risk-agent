"""Record 13-8-1 basic execution after original-cell and route checks."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID = "2026-정오표1차/기계설비/13-8-1/소각로설치"
INDEX = ROOT / "data/drafts/executable.json"
AUDIT = ROOT / "evals/runtime_validation/13-8-1-exact-process-source-audit-2026-10-19.json"
RECORD = ROOT / "evals/runtime_validation/executable-13-8-1-exact-routes-promotion-2026-10-19.json"


def main():
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["status"] == "passed"
    assert audit["source_cells"] == 32 and audit["exact_process_routes"] == 9
    assert not audit["inspection_rule_verified"]
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
        [key, count] for key, count in index["summary"]["failure_reasons_top10"] if count > 0]
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
        "root_cause": "The extracted process cells retained the numeric rates but lost the source's task-specific unit column and continuation-table boundary. The saved selector also used synthetic row labels rather than the exact source rows. Each of nine numeric processes now maps explicitly to its original table, full row, and unit; columns are the source trade labels. Runtime `trades_by_row` selects only the labor resources actually present in that exact source row.",
        "verification": str(AUDIT.relative_to(ROOT)),
        "source_evidence": "Original PDF physical p.891 / printed p.835 visually checked; 32 numeric labor cells independently transcribed against the page.",
        "runtime_change": "Opt-in per_unit trades_by_row exact source-row routing; no existing cached executable declares this branch.",
        "full_rule_verification": False,
        "remaining_limits": ["Inspection/calibration is stated as 10% of other work and is not a direct per-unit cell; it remains unimplemented and fails closed.",
                             "Other cited notes/usage equipment outside p.891 remain partial."],
        "focused_regressions": ["13-8-1: 32 source cells and nine exact process/table/row/unit calculations; inspection/calibration remains unresolved.",
                                "check_per_unit.py 44/44"],
        "counts_after_promotion": counts,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(counts, ensure_ascii=False))


if __name__ == "__main__":
    main()

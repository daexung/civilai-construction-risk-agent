"""Record 1-4-2 after denominator, cost-route, and original-cell audit."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID = "2026-정오표1차/건축/1-4-2/스터드볼트설치"
INDEX = ROOT / "data/drafts/executable.json"
AUDIT = ROOT / "evals/runtime_validation/1-4-2-source-basis-calc-audit-2026-10-19.json"
RECORD = ROOT / "evals/runtime_validation/executable-1-4-2-source-basis-promotion-2026-10-19.json"
REASON = "기본 조합 blocked: 이 할증 규칙은 아직 자동 계산하지 않음"


def main() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["status"] == "all_source_cells_and_declared_routes_verified"
    assert audit["source"]["rate_cells"] == 8 and audit["runtime"]["method_routes"] == 4
    assert audit["runtime"]["full_rules_verified"] is False
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    assert ID not in index["executable"]
    failures = [entry for entry in index["failed"] if entry.get("id") == ID]
    assert len(failures) == 1 and failures[0]["reason"] == REASON
    index["failed"] = [entry for entry in index["failed"] if entry.get("id") != ID]
    index["executable"] = sorted([*index["executable"], ID])
    for row in index["summary"]["failure_reasons_top10"]:
        if row[0] == REASON:
            assert row[1] == 25
            row[1] -= 1
            break
    else:
        raise AssertionError("failure class missing")
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
        "previous_failure_reason": REASON, "verification": str(AUDIT.relative_to(ROOT)),
        "root_cause": "The source denominator was already declared as 1,000개, but an unimplemented note_adjustment duplicated that conversion. The rule remains and is marked implemented by the source table basis. Cost rates are routed by the four exact installation_type values.",
        "source_recovery": "Eight original rate cells were compared to physical PDF p.632 / printed p.576, including both trades, both locations and both weld modes.",
        "full_calculation_rules_verified": False,
        "open": "Other than the two-column/top-down scope, the source leaves weld variants open; materials cost is 5% of principal material cost and stays unpriced without material amount.",
        "counts_after_promotion": counts,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(counts, ensure_ascii=False))


if __name__ == "__main__":
    main()

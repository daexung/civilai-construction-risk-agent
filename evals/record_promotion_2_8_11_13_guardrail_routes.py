"""Record both verified guardrail spacing-rate transitions."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "data/drafts/executable.json"
AUDIT = ROOT / "evals/runtime_validation/2-8-11-13-guardrail-rate-audit-2026-10-19.json"
REASON = "기본 조합 blocked: 이 할증 규칙은 아직 자동 계산하지 않음"
IDS = ["2026-정오표1차/공통/2-8-11/안전난간대설치및해체",
       "2026-정오표1차/공통/2-8-13/안전난간대설치및해체"]


def main() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["status"] == "both_source_rate_matrices_and_calculations_verified"
    assert audit["total_calculation_cases"] == 18 and audit["full_rules_verified"] is False
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    for item_id in IDS:
        assert item_id not in index["executable"]
        failures = [item for item in index["failed"] if item.get("id") == item_id]
        assert len(failures) == 1 and failures[0]["reason"] == REASON
    index["failed"] = [item for item in index["failed"] if item.get("id") not in IDS]
    index["executable"] = sorted([*index["executable"], *IDS])
    for row in index["summary"]["failure_reasons_top10"]:
        if row[0] == REASON:
            assert row[1] >= 2
            row[1] -= len(IDS)
            break
    else:
        raise AssertionError("failure class missing")
    index["summary"]["by_calc_type"]["per_unit"]["executable"] += len(IDS)
    index["summary"]["by_scope"]["공통/6장"]["executable"] += len(IDS)
    index["summary"]["executable"] = len(index["executable"])
    index["summary"]["failed"] = len(index["failed"])
    INDEX.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    counts = {"executable": len(index["executable"]), "failed": len(index["failed"]),
              "unsupported": index["summary"]["skipped_without_compatible_calculator"],
              "excluded": index["summary"]["excluded_from_execution"]}
    rows = []
    for section, item_id in zip(("2-8-11", "2-8-13"), IDS):
        detail = next(item for item in audit["source"] if item["section"] == section)
        rows.append({"id": item_id, "previous_status": "failed", "current_status": "executable",
                     "previous_failure_reason": REASON, "verification": str(AUDIT.relative_to(ROOT)),
                     "root_cause": "The exact 90/100/110% source table rates were only prose note_adjustments; they are now connected to existing per_unit source-backed base_rate_multipliers. The original note remains annotated as implemented by that route.",
                     "source_and_calculation_scope": detail,
                     "non_calculated_scope": "Protective net and toe board remain separate source items.",
                     "counts_after_both_promotions": counts})
        rec = ROOT / f"evals/runtime_validation/executable-{section}-guardrail-rate-promotion-2026-10-19.json"
        rec.write_text(json.dumps(rows[-1], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(counts, ensure_ascii=False))


if __name__ == "__main__":
    main()

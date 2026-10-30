"""Keep 7-4-1 joining calculable and block unquantified removal discount."""
from __future__ import annotations
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from pipeline.validate_drafts import load_chunks, file_sha256, validate_one

SPEC = ROOT / "data/drafts/specs/토목/7-4-1.json"
OUT = ROOT / "evals/runtime_validation/per-unit-7-4-1-policy-audit-2026-10-19.json"


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    draft = package["draft"]
    draft["inputs"] = [field for field in draft["inputs"] if field["name"] != "removal_discount_rate"]
    draft["quantity_model"]["params"]["note_adjustments"] = []
    draft["blocked"] = [item for item in draft.get("blocked", [])
                        if item.get("blocked_if", {}).get("input") != "work_type"]
    draft["blocked"].append({
        "condition": "work_type == '철거'",
        "blocked_if": {"input": "work_type", "op": "==", "value": "철거"},
        "reason": "원문은 인력과 장비 품을 최대 30%까지 감산한다고만 규정하며 구체적 감산률은 정하지 않는다. 임의 요율을 받지 않고 철거 계산을 보류한다.",
        "source": "PDF 393쪽 7-4-1 비고",
        "cite": {"table_id": "p449-t1"},
    })
    SPEC.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # All 14 diameter × 2 joint-method routes calculate for joining; all 28
    # removal routes remain explicitly blocked under the source's open rate.
    computed = blocked = 0
    examples = {}
    for diameter in [field for field in draft["inputs"] if field["name"] == "pipe_diameter"][0]["allowed_values"]:
        for joint in ("플랜지접합", "고무슬리브접합"):
            for work_type in ("접합", "철거"):
                result = per_unit(draft, {"pipe_diameter": diameter, "joint_type": joint,
                                          "work_type": work_type, "quantity": "1"})
                if work_type == "접합":
                    assert result.get("status") == "computed", (diameter, joint, result)
                    computed += 1
                else:
                    assert result.get("status") == "blocked", (diameter, joint, result)
                    blocked += 1
                examples.setdefault(work_type, result.get("status"))
    validation = validate_one(SPEC, ROOT / "data/drafts", load_chunks(ROOT / "data/processed/chunks.all.jsonl"),
                              file_sha256(ROOT / "data/processed/chunks.all.jsonl"))
    assert validation["ok"], validation
    report_path = ROOT / "data/drafts/report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    old = next(item for item in report["results"]
               if item["path"].replace("\\", "/") == "specs/토목/7-4-1.json")
    if old["ok"] != validation["ok"]:
        report["ok"] += 1 if validation["ok"] else -1
    for key in ("with_format_issues", "with_citation_issues"):
        field = key.replace("with_", "")
        report[key] += int(bool(validation[field])) - int(bool(old[field]))
    report["results"][report["results"].index(old)] = validation
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = {"table_id": "p449-t1", "source_cells": 14 * 4,
              "calculated_join_routes": computed, "blocked_removal_routes": blocked,
              "user_discount_input_removed": True, "validation_ok": validation["ok"],
              "examples": examples}
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Restore the omitted rust-state adjustment grid for maintenance 2-4-3."""
from __future__ import annotations

import json
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.tools.calc.price import price_unit, select_rate_version
from pipeline.validate_drafts import file_sha256, load_chunks, validate_one

SPEC = ROOT / "data/drafts/specs/유지관리/2-4-3.json"
TRADES = ["초급기술자", "특별인부", "보통인부", "일반기계운전사", "워터젯트", "윈치",
          "발전기", "물탱크(살수차)", "트럭탑재형크레인", "수중펌프"]
RUST_CITE = "본 품은 녹부착상태가 보통인 경우를 기준한 것이므로 다음에 따라 증감 적용한다."
COATED_CITE = "도복장 강관을 대상으로 할 경우 본 품의 80%를 계상한다."


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    draft = package["draft"]
    tables = draft["tables"]
    if not any(table["id"] == "p960-t1" for table in tables):
        tables.append({"id": "p960-t1", "role": "녹 부착 상태 적용(%)",
                       "source": "PDF 인쇄 904쪽, 녹 부착 상태 적용률 하위표",
                       "unit": "%", "values": {"적용(%)": {
                           "불량": "5", "보통": "0", "양호": "-5"}},
                       "cite": {"table_id": "p960-t1"}})
    rules = [{"when": {"pipe_material": "도복장 강관"}, "rate": "4/5",
              "operation": "multiply", "applies_to": TRADES,
              "application_cite": {"chunk_id": "p960-t0", "quote": COATED_CITE},
              "source": "PDF 인쇄 904쪽 표 비고, 도복장 강관 80%"}]
    for state, rate in (("불량", "1/20"), ("양호", "-1/20")):
        rules.append({"when": {"rust_condition": state}, "rate": rate,
                      "applies_to": TRADES,
                      "rate_table": {"id": "p960-t1", "row": "적용(%)", "column": state},
                      "application_cite": {"chunk_id": "p960-t0", "quote": RUST_CITE},
                      "source": "PDF 인쇄 904쪽 녹 부착 상태 적용(%) 표"})
    draft["quantity_model"]["params"]["surcharges"] = rules
    draft["quantity_model"]["steps"] = [
        "p960-t0에서 관경별 기본 인력·장비 품을 선택하고 물량(m)을 곱한다.",
        "도복장 강관은 원문에 따라 해당 인력·장비 품에 80% 승수를 적용한다.",
        "녹 부착 상태 표에서 불량 +5%, 보통 0%, 양호 -5%를 적용한다.",
        "재료 소모품 행은 원문 계수 그대로 산출하며 인력·장비 할증 대상에서 제외한다."]
    SPEC.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    cases = []
    for material, rust, factor in (
        ("주철관 및 강관", "보통", Fraction(1)),
        ("도복장 강관", "보통", Fraction(4, 5)),
        ("주철관 및 강관", "불량", Fraction(21, 20)),
        ("주철관 및 강관", "양호", Fraction(19, 20)),
        ("도복장 강관", "불량", Fraction(21, 25)),
        ("도복장 강관", "양호", Fraction(19, 25)),
    ):
        inputs = {"pipe_diameter": "150∼200", "quantity": "10",
                  "pipe_material": material, "rust_condition": rust}
        result = per_unit(draft, inputs)
        assert result.get("status") == "computed", (inputs, result)
        for line in result["unit_lines"]:
            if line["kind"] in ("labor", "equipment"):
                assert Fraction(line["exact"]) == Fraction(line["citations"][0]["value"]) * factor, (line, factor)
                assert len(line["citations"]) >= (1 if factor == 1 else 2), line
        priced = price_unit(draft, result["unit_lines"], select_rate_version("2026-10-01"),
                            inputs, "2026-10-01")
        assert priced.get("status") in ("COMPLETE", "PARTIAL"), priced
        assert priced["reference_amounts"]["volume"] == "10"
        cases.append({"inputs": inputs, "factor": str(factor), "status": result["status"],
                      "lines": result["unit_lines"], "price_status": priced["status"],
                      "reference_amounts": priced["reference_amounts"]})

    chunks_path = ROOT / "data/processed/chunks.all.jsonl"
    validation = validate_one(SPEC, ROOT / "data/drafts", load_chunks(chunks_path),
                              file_sha256(chunks_path))
    assert validation["ok"], validation
    report_path = ROOT / "data/drafts/report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    old = next(item for item in report["results"]
               if item["path"].replace("\\", "/") == "specs/유지관리/2-4-3.json")
    report["ok"] += int(validation["ok"]) - int(old["ok"])
    for key in ("with_format_issues", "with_citation_issues"):
        field = key.replace("with_", "")
        report[key] += int(bool(validation[field])) - int(bool(old[field]))
    report["results"][report["results"].index(old)] = validation
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    index_path = ROOT / "data/drafts/executable.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    ident = draft["id"]
    index["failed"] = [item for item in index["failed"] if item["id"] != ident]
    index["executable"] = sorted(set(index["executable"]) | {ident})
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    audit = {"id": ident, "source": {"physical_page": 960, "printed_page": 904,
             "visual_checked": "tmp/p960-2-4-3-source.png", "base_table": "p960-t0",
             "rust_grid": "p960-t1", "rust_values_percent": {"불량": 5, "보통": 0, "양호": -5},
             "coated_rule": COATED_CITE}, "cases": cases,
             "focused_validation_ok": validation["ok"],
             "scope": "base/source rule cases and offline pricing verified for normal and coated pipe with poor/normal/good rust; no inventory-wide rule completion claimed"}
    out = ROOT / "evals/runtime_validation/per-unit-maintenance-2-4-3-rust-adjustment-audit-2026-10-19.json"
    out.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"id": ident, "focused_validation_ok": validation["ok"],
                      "source_cells": 3, "scenarios": len(cases)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Connect the 9-5-3 50-model source unit directly to the table denominator."""
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

SPEC = ROOT / "data/drafts/specs/토목/9-5-3.json"
BASE = {"특급기술자": Fraction(2), "고급기술자": Fraction(13), "중급기술자": Fraction(10)}
QUOTE = "본 품은 연속된 항공사진 50모델을 1작업 단위로 한 것이다."


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    draft = package["draft"]
    table = next(item for item in draft["tables"] if item["id"] == "p529-t0")
    assert {name: Fraction(table["values"]["계"][name]) for name in BASE} == BASE
    fields = {field["name"]: field for field in draft["inputs"]}
    assert fields["models"]["unit"] == "모델"
    rate = draft["quantity_model"]["params"]["unit_rate_table"]
    rate["basis_by_row"] = {"계": "인/50모델"}
    rate["basis_cites_by_row"] = {"계": {"chunk_id": "p529-x4", "quote": QUOTE}}
    params = draft["quantity_model"]["params"]
    # The former memo is now represented by the explicit table denominator.
    params["note_adjustments"] = []
    draft["quantity_model"]["steps"] = [
        "p529-t0의 합계 인원은 연속 항공사진 50모델 1작업 단위에 해당한다.",
        "50모델 기준 인원수를 입력 models/50으로 환산하여 직종별 품을 산출한다.",
        "기계경비, 데이터 처리 프로그램, 재료비 등 별도 계상 항목은 산출하지 않는다."]
    SPEC.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    cases = []
    for amount in ("1", "25", "50", "100"):
        inputs = {"models": amount}
        result = per_unit(draft, inputs)
        assert result.get("status") == "computed", (inputs, result)
        actual = {line["name"]: Fraction(line["exact"]) for line in result["unit_lines"]}
        expected = {name: value / 50 for name, value in BASE.items()}
        assert actual == expected, (inputs, expected, actual)
        assert all(any(cite.get("quote") == QUOTE for cite in line["citations"])
                   for line in result["unit_lines"])
        priced = price_unit(draft, result["unit_lines"], select_rate_version("2026-10-01"),
                            inputs, "2026-10-01")
        assert priced.get("status") in ("COMPLETE", "PARTIAL"), priced
        assert priced["reference_amounts"]["volume"] == amount
        cases.append({"input_models": amount,
                      "expected_person_days_per_model": {name: str(value) for name, value in expected.items()},
                      "expected_total_person_days": {name: str(value * int(amount))
                                                     for name, value in expected.items()},
                      "actual_person_days": {name: line["exact"] for name, line in
                                             ((line["name"], line) for line in result["unit_lines"])},
                      "offline_price_status": priced["status"],
                      "reference_amounts": priced["reference_amounts"]})

    chunks_path = ROOT / "data/processed/chunks.all.jsonl"
    validation = validate_one(SPEC, ROOT / "data/drafts", load_chunks(chunks_path),
                              file_sha256(chunks_path))
    assert validation["ok"], validation
    report_path = ROOT / "data/drafts/report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    old = next(item for item in report["results"]
               if item["path"].replace("\\", "/") == "specs/토목/9-5-3.json")
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

    audit = {"id": ident, "source": {"physical_page": 529, "printed_page": 473,
             "visual_checked": "tmp/9-5-3-source-p529.png", "table": "p529-t0",
             "cells": {f"계/{name}": str(value) for name, value in BASE.items()},
             "basis_quote": QUOTE, "raw_denominator": "50모델/작업단위"},
             "cases": cases, "focused_validation_ok": validation["ok"],
             "scope": "all three original labor totals, exact 50-model denominator, quantities 1/25/50/100, citations and offline pricing verified; separately accounted equipment/program/material costs remain excluded"}
    out = ROOT / "evals/runtime_validation/per-unit-9-5-3-fifty-model-source-audit-2026-10-19.json"
    out.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"id": ident, "focused_validation_ok": validation["ok"],
                      "numeric_cells": len(BASE), "model_routes": len(cases)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

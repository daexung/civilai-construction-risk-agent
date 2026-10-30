"""Route 13-9-4 exact work rows, heterogeneous denominators, and source dashes."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.tools.calc.price import price_unit, select_rate_version
from pipeline.validate_drafts import file_sha256, load_chunks, validate_one

SPEC = ROOT / "data/drafts/specs/기계설비/13-9-4.json"
ROUTES = {
    "오수처리시설": {"unit": "조", "rates": {"위생공": "4.13", "보통인부": "4.13"},
                     "excluded": ["계장공"]},
    "제어함": {"unit": "개", "rates": {"계장공": "3.75"},
                "excluded": ["위생공", "보통인부"]},
}


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    draft = package["draft"]
    table = next(item for item in draft["tables"] if item["id"] == "p900-t2")
    rate = draft["quantity_model"]["params"]["unit_rate_table"]
    assert table["values"]["오수처리시설"]["위생공"] == "4.13"
    assert table["values"]["오수처리시설"]["보통인부"] == "4.13"
    assert table["values"]["제어함"]["계장공"] == "3.75"
    assert table["values"]["오수처리시설"]["단위"] == "인/조"
    assert table["values"]["제어함"]["단위"] == "인/개"

    rate.pop("column_input", None)
    rate["quantity_unit_selector"] = {
        "input": "work_type", "values": {"오수처리시설": "조", "제어함": "개"}}
    draft["quantity_model"]["params"]["excluded_resources"] = [
        {"trade": trade, "when": {"work_type": row},
         "source": f"p900-t2 {row}/{trade} 원문 셀 대시; 해당 작업행의 적용 직종 아님",
         "cite": {"table_id": "p900-t2", "row": row, "column": trade, "value": "-"}}
        for row, route in ROUTES.items() for trade in route["excluded"]]
    SPEC.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    cases = []
    for work_type, route in ROUTES.items():
        inputs = {"work_type": work_type, "quantity": "2"}
        result = per_unit(draft, inputs)
        assert result.get("status") == "computed", (inputs, result)
        actual = {line["name"]: line["applied"] for line in result["unit_lines"]}
        assert actual == route["rates"], (inputs, actual, route["rates"])
        assert all(line["unit"].endswith(f"/{route['unit']}") for line in result["unit_lines"])
        for line in result["unit_lines"]:
            assert any(cite.get("value") == next(v for v in table["values"][work_type].values()
                                                     if v == route["rates"][line["name"]])
                       for cite in line["citations"])
        excluded = result["provenance"]["excluded_resources"]
        assert {entry["trade"] for entry in excluded} == set(route["excluded"])
        assert all(any(cite.get("value") == "-" for cite in entry["citations"])
                   for entry in excluded)
        priced = price_unit(draft, result["unit_lines"], select_rate_version("2026-10-01"),
                            inputs, "2026-10-01")
        assert priced.get("status") in ("COMPLETE", "PARTIAL"), priced
        assert priced["reference_amounts"]["volume"] == "2"
        cases.append({"inputs": inputs, "unit": route["unit"], "unit_rates": actual,
                      "excluded_source_dashes": excluded,
                      "price_status": priced["status"],
                      "priced_quantities": {line["name"]: line["quantity"] for line in priced["lines"]},
                      "reference_amounts": priced["reference_amounts"]})

    chunks_path = ROOT / "data/processed/chunks.all.jsonl"
    validation = validate_one(SPEC, ROOT / "data/drafts", load_chunks(chunks_path),
                              file_sha256(chunks_path))
    assert validation["ok"], validation
    report_path = ROOT / "data/drafts/report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    old = next(item for item in report["results"]
               if item["path"].replace("\\", "/") == "specs/기계설비/13-9-4.json")
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

    audit = {"id": ident, "source": {"physical_page": 900, "printed_page": 844,
             "visual_checked": "tmp/13-9-4-source-p900.png", "table": "p900-t2",
             "rates": {row: route["rates"] for row, route in ROUTES.items()},
             "units": {"오수처리시설": "인/조", "제어함": "인/개"},
             "dashes": {row: route["excluded"] for row, route in ROUTES.items()}},
             "cases": cases, "focused_validation_ok": validation["ok"],
             "scope": "two exact work rows, all three numeric cells, both source denominators and three explicit dash exclusions verified; equipment separate and all-rule inventory coverage not claimed"}
    out = ROOT / "evals/runtime_validation/per-unit-13-9-4-work-unit-source-audit-2026-10-19.json"
    out.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"id": ident, "focused_validation_ok": validation["ok"],
                      "numeric_cells": 3, "work_unit_routes": len(cases),
                      "explicit_dash_exclusions": sum(len(v["excluded"]) for v in ROUTES.values())},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Bind the explicit one-map source basis to the 9-17-1 total row."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.tools.calc.price import price_unit, select_rate_version
from pipeline.validate_drafts import file_sha256, load_chunks, validate_one

SPEC = ROOT / "data/drafts/specs/토목/9-17-1.json"
TABLE = "p615-t0"
NOTE = "본 품은 지적도 크기의 1매를 기준으로 한 것이다."


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    draft = package["draft"]
    rate = draft["quantity_model"]["params"]["unit_rate_table"]
    assert rate["table"] == TABLE
    assert draft["inputs"][0]["name"] == "quantity" and draft["inputs"][0]["unit"] == "매"
    source = next(table for table in draft["tables"] if table["id"] == TABLE)
    assert source["unit"] == "인·일"
    assert source["values"]["합계"]["인원수 합계 지적기사"] == "(0.21)"
    assert source["values"]["합계"]["인원수 지적산업기사"] == "(0.65)"
    rate["basis_by_row"] = {"합계": "1매"}
    # These are resource columns; let the runtime bind each declared trade to
    # the one source column that names it instead of using a composite column selector.
    rate.pop("column_input", None)
    rate["parenthetical_value_selector"] = {
        "mode": "parenthetical_only",
        "source": "PDF printed p.559 table note: parenthesized workdays indicate office work; this table's total cells are parenthetical values.",
        "cite": {"chunk_id": TABLE, "quote": "( )는 내업임"},
    }
    adjustment = draft["quantity_model"]["params"]["surcharges"][0]
    adjustment["operation"] = "multiply"
    adjustment["rate_table"] = {"id": "p615-t1", "row": "계수", "column": "임야"}
    adjustment["application_cite"] = {
        "chunk_id": "p615-x10",
        "quote": "지적공부 등록지(토지, 임야)별로 다음의 계수를 곱하여 계상한다.",
    }
    SPEC.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    source_text = next(json.loads(line)["text"]
                       for line in (ROOT / "data/processed/chunks.all.jsonl").read_text(encoding="utf-8").splitlines()
                       if line.strip() and json.loads(line).get("chunk_id") == "p615-x13")
    assert NOTE in source_text, source_text

    # Exact source cells × exact quantities. The table total is per one map sheet.
    routes = []
    for quantity in ("1", "10"):
        for land_type in ("토지", "임야"):
            inputs = {"quantity": quantity, "land_type": land_type,
                      "paper_size": "기준규격", "special_paper": False}
            result = per_unit(draft, inputs)
            assert result.get("status") == "computed", result
            factor = __import__("fractions").Fraction("1") if land_type == "토지" else __import__("fractions").Fraction("1.28")
            labor = {line["name"]: line["applied"] for line in result["unit_lines"]}
            assert labor["지적기사"] == str(__import__("backend.agent.tools.calc.daily_crew", fromlist=["_exact_text"])._exact_text(__import__("fractions").Fraction("0.21") * factor)), labor
            assert labor["지적산업기사"] == str(__import__("backend.agent.tools.calc.daily_crew", fromlist=["_exact_text"])._exact_text(__import__("fractions").Fraction("0.65") * factor)), labor
            priced = price_unit(draft, result["unit_lines"], select_rate_version("2026-10-01"), inputs, "2026-10-01")
            assert priced.get("status") in ("COMPLETE", "PARTIAL"), priced
            assert {line["name"]: line["quantity"] for line in priced["lines"]} == labor
            routes.append({"quantity_map": quantity, "land_type": land_type, "computed_unit_labor": labor,
                           "priced_line_quantities": {line["name"]: line["quantity"] for line in priced["lines"]},
                           "price_status": priced["status"]})

    validation = validate_one(SPEC, ROOT / "data/drafts", load_chunks(ROOT / "data/processed/chunks.all.jsonl"),
                              file_sha256(ROOT / "data/processed/chunks.all.jsonl"))
    assert validation["ok"], validation
    report_path = ROOT / "data/drafts/report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    old = next(item for item in report["results"]
               if item["path"].replace("\\", "/") == "specs/토목/9-17-1.json")
    if old["ok"] != validation["ok"]:
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

    artifact = {"method": "explicit one-map denominator mapped from cited source note; exact table cells checked; no fuzzy mapping",
                "id": ident, "table": TABLE, "source_note_chunk": "p615-x13", "source_note": NOTE,
                "basis_by_row": rate["basis_by_row"], "unit_source_cells": source["values"]["합계"],
                "calculation_routes": routes, "focused_validation_ok": validation["ok"],
                "scope": "basis/unit/rate selection only; remaining paper-fee and material/equipment rules not all verified"}
    out = ROOT / "evals/runtime_validation/per-unit-9-17-1-explicit-source-basis-2026-10-19.json"
    out.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in artifact.items() if k != "calculation_routes"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

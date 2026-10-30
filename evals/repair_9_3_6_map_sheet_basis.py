"""Recover the cited one-map basis and office-only totals for 9-3-6."""
from __future__ import annotations

import json
import re
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.daily_crew import _exact_text
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.tools.calc.price import price_unit, select_rate_version
from pipeline.validate_drafts import file_sha256, load_chunks, validate_one

SPEC = ROOT / "data/drafts/specs/토목/9-3-6.json"
TABLE = "p509-t0"
EXPECTED = {"지적기사": "0.17", "지적산업기사": "0.36"}
SOURCE_CELLS = {"지적기사": "(0.17)", "지적산업기사": "(0.36)"}
REGISTER_FACTOR = "p509-t1"
REGISTER_NOTE = "지적공부 등록지(토지, 임야)별로 다음의 계수를 곱하여 계상한다."
MAP_BASIS_NOTE = "본 품은 지적도 크기의 1장을 기준으로 한 것이다."
PARENTHETICAL_NOTE = "( )는 내업임"


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    draft = package["draft"]
    params = draft["quantity_model"]["params"]
    rate = params["unit_rate_table"]
    assert rate["table"] == TABLE
    source = next(table for table in draft["tables"] if table["id"] == TABLE)
    assert source["unit"] == "인"
    assert source["values"]["합계"] == EXPECTED

    rate["basis_by_row"] = {"합계": "1장"}
    rate["parenthetical_value_selector"] = {
        "mode": "parenthetical_only",
        "source": "PDF printed p.453: the table states values in parentheses are for office work.",
        "cite": {"chunk_id": TABLE, "quote": PARENTHETICAL_NOTE},
    }
    params["surcharges"] = [{
        "when": {"land_type": "임야"}, "rate": "1.28", "operation": "multiply",
        "rate_table": {"id": REGISTER_FACTOR, "row": "계수", "column": "임야"},
        "application_cite": {"chunk_id": "p509-x9", "quote": REGISTER_NOTE},
        "applies_to": list(EXPECTED),
        "source": "PDF printed p.453 [주] ①, p509-t1 registration coefficient table",
    }]
    params["note_adjustments"] = []
    SPEC.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    chunk_map = {json.loads(line)["chunk_id"]: json.loads(line)
                 for line in (ROOT / "data/processed/chunks.all.jsonl").read_text(encoding="utf-8").splitlines()
                 if line.strip()}
    assert MAP_BASIS_NOTE in chunk_map["p509-x12"]["text"]
    assert "( )는" in chunk_map[TABLE]["text"] and "내업임" in chunk_map[TABLE]["text"]
    assert "1.00" in chunk_map[REGISTER_FACTOR]["text"] and "1.28" in chunk_map[REGISTER_FACTOR]["text"]
    assert "곱하여 계상한다" in chunk_map["p509-x9"]["text"]

    cases = []
    for quantity in ("1", "10"):
        for land_type, factor in (("토지", Fraction(1)), ("임야", Fraction("1.28"))):
            inputs = {"land_type": land_type, "quantity": quantity}
            result = per_unit(draft, inputs)
            assert result.get("status") == "computed", (inputs, result)
            expected = {trade: _exact_text(Fraction(raw) * factor)
                        for trade, raw in EXPECTED.items()}
            actual = {line["name"]: line["applied"] for line in result["unit_lines"]}
            assert actual == expected, (inputs, expected, actual)
            priced = price_unit(draft, result["unit_lines"], select_rate_version("2026-10-01"),
                                inputs, "2026-10-01")
            assert priced.get("status") in ("COMPLETE", "PARTIAL"), priced
            cases.append({"inputs": inputs, "expected_unit_rates": expected, "actual_unit_rates": actual,
                          "price_status": priced["status"],
                          "price_line_quantities": {line["name"]: line["quantity"] for line in priced["lines"]}})

    chunks_path = ROOT / "data/processed/chunks.all.jsonl"
    validation = validate_one(SPEC, ROOT / "data/drafts", load_chunks(chunks_path), file_sha256(chunks_path))
    assert validation["ok"], validation
    report_path = ROOT / "data/drafts/report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    old = next(item for item in report["results"]
               if item["path"].replace("\\", "/") == "specs/토목/9-3-6.json")
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

    artifact = {"id": ident, "physical_page": 509, "printed_page": 453,
                "source_visual": "tmp/9-3-6-source-p509.png", "table": TABLE,
                "modeled_total_cells": EXPECTED, "original_pdf_cells": SOURCE_CELLS,
                "parenthetical_note": PARENTHETICAL_NOTE,
                "source_map_basis_note": MAP_BASIS_NOTE, "registration_factor_table": REGISTER_FACTOR,
                "registration_factor_application": REGISTER_NOTE, "calculation_cases": cases,
                "focused_validation_ok": validation["ok"],
                "scope": "one-map basis, office-value selection, land registration factor and focused price routing; separate equipment/material pricing remains excluded by source note"}
    out = ROOT / "evals/runtime_validation/per-unit-9-3-6-map-sheet-source-audit-2026-10-19.json"
    out.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"id": ident, "focused_validation_ok": validation["ok"],
                      "cases": len(cases), "source_cells": EXPECTED}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

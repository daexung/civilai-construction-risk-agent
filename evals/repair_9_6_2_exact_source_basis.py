"""Route 9-6-2's explicit 50-point basis and source coefficient table."""
from __future__ import annotations
import copy
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pymupdf
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.tools.source.citation import resolve_cites
from pipeline.validate_drafts import load_chunks, file_sha256, validate_one

SPEC = ROOT / "data/drafts/specs/토목/9-6-2.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
OUT = ROOT / "evals/runtime_validation/per-unit-9-6-2-source-audit-2026-10-19.json"


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    draft = package["draft"]
    rate = draft["quantity_model"]["params"]["unit_rate_table"]
    rate["column_input_by_table"] = {"p578-t1": None}
    table = next(item for item in draft["tables"] if item["id"] == "p578-t1")
    table["unit"] = "인/50점"  # [기타사항] ㉮: all coefficients use 50 points.
    draft["quantity_model"]["params"]["surcharges"] = []
    draft["quantity_model"]["params"].pop("base_rate_multipliers", None)
    rate["base_rate_multipliers"] = [{
        "when": {"survey_method": "배각법"}, "factor": "1.37",
        "cite": {"table_id": "p579-t0", "row": "배각법", "column": "계수", "value": "1.37"},
    }]
    draft["quantity_model"]["params"]["note_adjustments"] = []
    for item in draft.get("not_calculated", []):
        cite = item.get("cite", {})
        if cite.get("chunk_id") == "p579-x5" and "지적삼각측량비를" in cite.get("quote", ""):
            cite["quote"] = "지적삼각측량비를 별도"
    SPEC.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Audit source table rates and the 50-point denominator directly against
    # original PDF grids/text; the coefficient is kept as a source citation.
    with pymupdf.open(PDF) as doc:
        grid = doc[577].find_tables().tables[1].extract()
        coeff = doc[578].find_tables().tables[0].extract()
        p578_text = doc[577].get_text("text")
        p579_text = doc[578].get_text("text")
    assert list(table["values"]) == ["합계"]
    source_values = table["values"]["합계"]
    assert len(grid) == 18 and len(grid[0]) == 12
    # The spec's source columns correspond to the total columns of the table.
    total_row = next(row for row in grid[1:] if row and "".join((row[0] or "").split()) == "합계")
    source_total_cells = [cell.strip() for cell in total_row[7:11]]
    spec_total = []
    for trade in rate["trades"]:
        matches = [value for column, value in source_values.items()
                   if "".join(trade.split()) in "".join(column.split())]
        assert len(matches) == 1, (trade, matches)
        spec_total.append(matches[0])
    assert spec_total == source_total_cells, (spec_total, source_total_cells)
    assert "도근점 50점을 기준" in p579_text
    assert "".join(coeff[2][0].split()) == "배각법" and coeff[2][1].strip() == "1.37"
    cite = resolve_cites(rate["base_rate_multipliers"][0]["cite"])
    assert cite and cite[0]["value"] == "1.37"
    # Every persisted citation is resolvable and the repaired quote occurs
    # verbatim in the saved source chunk.
    citation_count = 0
    for group in ("tables", "not_calculated", "blocked"):
        for item in draft.get(group, []):
            if item.get("cite"):
                citation_count += len(resolve_cites(item["cite"]))

    results = []
    for points in (50, 300):
        for method in ("방위각법", "배각법"):
            result = per_unit(draft, {"quantity": str(points), "survey_method": method})
            assert result.get("status") == "computed", (points, method, result)
            assert len(result["unit_lines"]) == 4
            results.append({"points": points, "method": method, "status": result["status"],
                            "values": {line["name"]: line["exact"] for line in result["unit_lines"]}})
    base = results[0]["values"]
    expected_50 = {"지적기사": "21/250", "지적산업기사": "343/625",
                   "지적기능사": "203/1250", "인부": "49/1250"}
    assert base == expected_50, base
    expected_baegak = {name: str(__import__("fractions").Fraction(value) * __import__("fractions").Fraction(137, 100))
                       for name, value in expected_50.items()}
    assert results[1]["values"] == expected_baegak, results[1]
    validation = validate_one(SPEC, ROOT / "data/drafts", load_chunks(ROOT / "data/processed/chunks.all.jsonl"),
                              file_sha256(ROOT / "data/processed/chunks.all.jsonl"))
    assert validation["ok"], validation
    validation_report_path = ROOT / "data/drafts/report.json"
    validation_report = json.loads(validation_report_path.read_text(encoding="utf-8"))
    previous = next(item for item in validation_report["results"]
                    if item["path"].replace("\\", "/") == "specs/토목/9-6-2.json")
    if not previous["ok"]:
        validation_report["ok"] += 1
    validation_report["with_citation_issues"] -= bool(previous["citation_issues"])
    validation_report["results"][validation_report["results"].index(previous)] = validation
    validation_report_path.write_text(json.dumps(validation_report, ensure_ascii=False, indent=2) + "\n",
                                      encoding="utf-8")
    report = {"source_table": "p578-t1", "coefficient_table": "p579-t0",
              "source_basis": "50점 (PDF 523쪽 ④ 기타사항 ㉮)",
              "source_cell_checks": 4, "resolved_citations": citation_count,
              "calculator_routes": len(results), "calculator_status_counts": {"computed": 4},
              "results": results}
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Connect the independently table-driven coefficients in 9-10-1."""
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


def main():
    path = ROOT / "data/drafts/specs/토목/9-10-1.json"
    package = json.loads(path.read_text(encoding="utf-8"))
    draft = package["draft"]
    table = next(t for t in draft["tables"] if t["id"] == "p594-t0")
    table["unit"] = "인·일/필지"
    trades = list(table["values"]["합계"])
    params = draft["quantity_model"]["params"]
    params["unit_rate_table"] = {
        "table": "p594-t0", "row_input": None, "column_input": None,
        "trades": trades, "trade_in_columns": True,
        "row_by_trade": {trade: "합계" for trade in trades},
        "basis_cites_by_row": {"합계": {
            "chunk_id": "p594-x10",
            "quote": "본 품은 1필지당 토지는 1,500㎡, 임야는 5,000㎡를 기준으로 하였으며, 기준면적 이하는 기준면적을 적용하고, 기준면적을 초과할 때에는 다음의 계수를 곱하여 계상한다."
        }}
    }
    params["quantity_input"] = "parcel_count"
    params["surcharges"] = []
    params["note_adjustments"] = []
    params["coefficient_combination"] = "multiply"
    params["coefficient_rules"] = [
        {"kind": "area_increment", "table": "p594-t1", "row": "계수",
         "area_input": "area", "land_input": "land_type",
         "base_area_by_value": {"토지": "1500", "임야": "5000"},
         "cite": {"chunk_id": "p594-x14",
                  "quote": "※ n은 가산횟수로 (대상면적-기준면적) ÷ 기준면적"}},
        {"table": "p594-t2", "row": "계수", "input": "land_type",
         "cite": {"chunk_id": "p594-x14",
                  "quote": "지적공부 등록지(토지, 임야)별로 다음의 계수를 곱하여 계상한다."}},
        {"table": "p594-t3", "row": "계수", "input": "region_type",
         "cite": {"chunk_id": "p594-x17",
                  "quote": "본 품은 면지역을 기준으로 하였으며, 행정구역이 다를 경우 다음의 계수를 곱하여 품을 계상한다."}}
    ]
    draft["quantity_model"]["steps"] = [
        "p594-t0 합계행에서 직종별 1필지 기본 품을 조회한다.",
        "토지 1,500㎡ 또는 임야 5,000㎡의 기준에 따라 면적 가산횟수 n과 p594-t1 계수를 구한다.",
        "등록지 p594-t2와 행정구역 p594-t3의 계수를 조회한다.",
        "원문에서 각 계수를 곱하여 품을 계상하므로 기본 품에 면적·등록·지역 계수를 모두 곱한다.",
        "단위당 직종별 품에 필지 수를 반영한다."
    ]
    package["draft"] = draft
    path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    scenarios = [
        ({"parcel_count": "1", "land_type": "토지", "area": "1500", "region_type": "면"}, Fraction(1),
         ["0.69", "0.76", "0.41"]),
        ({"parcel_count": "1", "land_type": "토지", "area": "3000", "region_type": "읍"}, Fraction(143, 100),
         ["0.9867", "1.0868", "0.5863"]),
        ({"parcel_count": "2", "land_type": "임야", "area": "15000", "region_type": "동 시"}, Fraction(273, 125),
         ["1.50696", "1.65984", "0.89544"])
    ]
    rates = [Fraction("0.69"), Fraction("0.76"), Fraction("0.41")]
    records = []
    for inputs, factor, printed in scenarios:
        result = per_unit(draft, inputs)
        assert result.get("status") == "computed", (inputs, result)
        actual = [Fraction(line["exact"]) for line in result["unit_lines"]]
        expected = [x * factor for x in rates]
        assert actual == expected == [Fraction(x) for x in printed], (inputs, actual, expected, printed)
        priced = price_unit(draft, result["unit_lines"], select_rate_version("2026-10-01"),
                            inputs, "2026-10-01")
        assert priced.get("status") in ("COMPLETE", "PARTIAL"), priced
        records.append({"inputs": inputs, "expected": [str(x) for x in expected],
                        "unit_lines": result["unit_lines"], "offline_price_status": priced["status"]})

    chunks = ROOT / "data/processed/chunks.all.jsonl"
    validation = validate_one(path, ROOT / "data/drafts", load_chunks(chunks), file_sha256(chunks))
    assert validation["ok"], validation
    report_path = ROOT / "data/drafts/report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    rel = path.relative_to(ROOT / "data/drafts").as_posix()
    old = next(x for x in report["results"] if x["path"].replace("\\", "/") == rel)
    report["ok"] += int(validation["ok"]) - int(old["ok"])
    for key in ("with_format_issues", "with_citation_issues"):
        field = key.removeprefix("with_")
        report[key] += int(bool(validation[field])) - int(bool(old[field]))
    report["results"][report["results"].index(old)] = validation
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    index_path = ROOT / "data/drafts/executable.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    ident = draft["id"]
    index["failed"] = [x for x in index["failed"] if x["id"] != ident]
    index["executable"] = sorted(set(index["executable"]) | {ident})
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out = ROOT / "evals/runtime_validation/per-unit-9-10-1-source-coefficient-product-audit-2026-10-19.json"
    out.write_text(json.dumps({
        "section": "9-10-1", "physical_pages": [594, 595],
        "source_images": ["tmp/focus-594.png", "tmp/focus-595.png"],
        "source_cells_checked": 12, "scenarios": records,
        "scope": "Visually checked the original p594 base totals and all area, registration and region coefficient cells. The source explicitly says each coefficient is multiplied into the quantity, so this route uses products, not additive deltas. Independent rational cases cover area threshold, one increment, and multiple increments with a forest registration and region multiplier; offline price routing was checked."
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"section": "9-10-1", "focused_validation_ok": validation["ok"],
                      "source_cells": 12, "cases": len(records)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

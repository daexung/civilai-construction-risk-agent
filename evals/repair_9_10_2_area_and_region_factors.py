"""Connect source-defined per-parcel area and region factors in 9-10-2."""
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
    path = ROOT / "data/drafts/specs/토목/9-10-2.json"
    package = json.loads(path.read_text(encoding="utf-8"))
    draft = package["draft"]
    table = next(t for t in draft["tables"] if t["id"] == "p595-t0")
    table["unit"] = "인/필지"
    trades = list(table["values"]["합계"])
    rate = draft["quantity_model"]["params"]["unit_rate_table"]
    rate.pop("basis_by_row", None)
    rate.update({"table": "p595-t0", "row_input": None, "column_input": None,
        "trades": trades, "trade_in_columns": True,
        "row_by_trade": {trade: "합계" for trade in trades},
        "basis_cites_by_row": {"합계": {"chunk_id": "p595-x13",
            "quote": "본 품은 1필지당 1,500㎡를 기준으로 하였으며, 기준면적 이하는 기준면적을 적용하고, 기준면적을 초과할 때에는 다음의 계수를 곱하여 계상한다."}}})
    params = draft["quantity_model"]["params"]
    params["quantity_input"] = "quantity"
    params["coefficient_combination"] = "multiply"
    params["coefficient_rules"] = [
        {"kind": "area_increment", "table": "p595-t1", "row": "계수",
         "area_input": "area", "base_area": "1500",
         "cite": {"chunk_id": "p595-x17",
                  "quote": "n은 가산횟수로 (대상면적-기준면적) ÷ 기준면적"}},
        {"table": "p596-t0", "row": "계수", "input": "region",
         "cite": {"chunk_id": "p596-x0",
                  "quote": "본 품은 면지역을 기준으로 하였으며, 행정구역이 다를 경우 다음의 계수를 곱하여 품을 계상한다."}},
    ]
    params["note_adjustments"] = []
    draft["quantity_model"]["steps"] = [
        "합계 직종별 품은 1필지 기준이다. 필지당 1,500㎡를 기준으로 면적계수를 산정한다.",
        "면적이 기준면적 이하이면 1.0, 초과분은 n=ceil((면적-1,500)/1,500)회로 산출한다. n=1은 원문 1회 셀, n≥2는 원문 1.2+0.10×n 식을 적용한다.",
        "면지역 외에는 읍/동시/동구의 원문 지역계수를 곱한다. 면적계수와 지역계수는 각각 원문에 따라 기본 품에 곱한다.",
        "직종별 단위당 품에 필지 수를 곱해 공량을 산출한다."]
    package["draft"] = draft
    path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    scenarios = [(1, 1500, "면"), (2, 3000, "읍"), (1, 4500, "동 시"), (3, 7000, "동 구")]
    records = []
    source_rates = [Fraction(x) for x in ("0.72", "0.80", "0.45")]
    region_factors = {"면": Fraction(1), "읍": Fraction(11, 10),
                      "동 시": Fraction(13, 10), "동 구": Fraction(14, 10)}
    for parcel_count, area, region in scenarios:
        inputs = {"quantity": str(parcel_count), "area": str(area), "region": region}
        result = per_unit(draft, inputs)
        assert result.get("status") == "computed", result
        n = max(0, -(-(area - 1500) // 1500)) if area > 1500 else 0
        area_factor = Fraction(1) if n == 0 else Fraction(13, 10) if n == 1 else Fraction(12, 10) + Fraction(n, 10)
        expected = [value * area_factor * region_factors[region] for value in source_rates]
        actual = [Fraction(line["exact"]) for line in result["unit_lines"]]
        assert actual == expected, (inputs, actual, expected)
        assert all(any(c.get("internal_id") in ("p595-t0", "p595-t1", "p596-t0")
                       or c.get("internal_id") in ("p595-x13", "p595-x17", "p596-x0")
                       for c in line["citations"]) for line in result["unit_lines"])
        priced = price_unit(draft, result["unit_lines"], select_rate_version("2026-10-01"), inputs, "2026-10-01")
        assert priced.get("status") in ("COMPLETE", "PARTIAL"), priced
        records.append({"inputs": inputs, "area_increment_count": n,
                        "area_factor": str(area_factor), "region_factor": str(region_factors[region]),
                        "independent_exact_results": [str(value) for value in expected],
                        "independent_total_after_parcel_quantity": [str(value * parcel_count) for value in expected],
                        "unit_lines": result["unit_lines"], "offline_price_status": priced["status"],
                        "reference_amounts": priced["reference_amounts"]})

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
    audit = {"section": "9-10-2", "physical_pages": [595, 596],
        "source_images": ["tmp/9-10-2-source-p595.png", "tmp/9-10-2-source-p596.png"],
        "source_cells_checked": 9, "scenarios": records,
        "scope": "Printed p.539-540 visually checked: three source labor totals, 1,500㎡ per parcel rule, 1.3 one-increment cell, 1.2+0.10×n multi-increment cell and four exact region coefficients. Four independent rational scenarios cover the threshold, one increment, two increments and n=4; coefficients multiply as the source says. Each case was priced offline. No unspecified rule was added."}
    out = ROOT / "evals/runtime_validation/per-unit-9-10-2-area-region-factor-audit-2026-10-19.json"
    out.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"section": "9-10-2", "focused_validation_ok": validation["ok"],
                      "source_cells": 9, "cases": len(records), "n_values": [r["area_increment_count"] for r in records]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

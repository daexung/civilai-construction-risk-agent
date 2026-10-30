"""Connect 9-8-2 work-type rows and source coefficient products."""
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
    path = ROOT / "data/drafts/specs/토목/9-8-2.json"
    package = json.loads(path.read_text(encoding="utf-8"))
    draft = package["draft"]
    table = next(t for t in draft["tables"] if t["id"] == "p589-t0")
    table["unit"] = "인/필지"
    trades = ["지적기사", "지적산업기사", "지적기능사"]
    params = draft["quantity_model"]["params"]
    params["unit_rate_table"] = {
        "table": "p589-t0", "row_input": "work_type", "trades": trades,
        "trades_by_row": {"외업": trades, "내업": trades[:2], "합계": trades},
        "basis_cites_by_row": {row: {
            "chunk_id": "p589-x10",
            "quote": "본 품은 1필지당 1,500㎡를 기준으로 하였으며, 기준면적 이하는 기준면적을 적용하고 기준면적을 초과할 때에는 다음의 계수를 곱하여 계상한다."
        } for row in ("외업", "내업", "합계")},
        "parenthetical_value_selector": {
            "mode": "parenthetical_only",
            "source": "원문에서 괄호는 내업임을 나타낸다.",
            "cite": {"chunk_id": "p589-t0", "quote": "( )는 내업"}
        }
    }
    params["quantity_input"] = "parcel_count"
    params["surcharges"] = []
    params["note_adjustments"] = []
    params["coefficient_combination"] = "multiply"
    params["coefficient_rules"] = [
        {"kind": "area_increment", "table": "p589-t1", "row": "계수",
         "area_input": "area", "base_area": "1500",
         "cite": {"chunk_id": "p589-x14",
                  "quote": "※ n은 가산횟수로 (대상면적-기준면적) ÷ 기준면적"}},
        {"table": "p589-t2", "row": "계수", "input": "region",
         "cite": {"chunk_id": "p589-x14",
                  "quote": "본 품은 면지역을 기준으로 하였으며, 행정구역이 다를 경우 다음의 계수를 곱하여 품을 계상한다."}}
    ]
    draft["quantity_model"]["steps"] = [
        "work_type에 따라 p589-t0의 외업, 내업 또는 합계 행을 선택한다.",
        "괄호 수량은 원문 표 주석에 따라 내업 수량으로 읽으며, 내업 행에서는 괄호값이 있는 직종만 산출한다.",
        "1,500㎡ 기준 면적계수와 지역계수를 해당 원문 표에서 조회하고 각 계수를 품에 곱한다.",
        "1필지당 직종별 품에 필지 수를 반영한다."
    ]
    package["draft"] = draft
    path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    base = {
        "외업": [Fraction("0.51"), Fraction("0.47"), Fraction("0.46")],
        "내업": [Fraction("0.24"), Fraction("0.34")],
        "합계": [Fraction("0.75"), Fraction("0.81"), Fraction("0.46")]
    }
    scenarios = []
    for work_type in ("외업", "내업", "합계"):
        scenarios.append(({"parcel_count": "1", "area": "1500", "region": "면",
                           "work_type": work_type}, Fraction(1), base[work_type]))
    scenarios.append(({"parcel_count": "2", "area": "3000", "region": "읍",
                       "work_type": "합계"}, Fraction(143, 100),
                      [x * Fraction(143, 100) for x in base["합계"]]))
    records = []
    for inputs, factor, expected in scenarios:
        result = per_unit(draft, inputs)
        assert result.get("status") == "computed", (inputs, result)
        actual = [Fraction(line["exact"]) for line in result["unit_lines"]]
        assert actual == expected, (inputs, actual, expected)
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
    out = ROOT / "evals/runtime_validation/per-unit-9-8-2-work-type-coefficient-audit-2026-10-19.json"
    out.write_text(json.dumps({
        "section": "9-8-2", "physical_pages": [589, 590],
        "source_images": ["tmp/focus-589.png", "tmp/focus-590.png"],
        "source_cells_checked": 15, "scenarios": records,
        "scope": "Visually compared the original source rates, the row note that parentheses indicate internal work, all area coefficient cells, all region coefficients, and per-parcel basis. Independently checked 외업, 내업 and 합계 paths; the source states area and region coefficients multiply into the quantity. Offline price routing was checked."
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"section": "9-8-2", "focused_validation_ok": validation["ok"],
                      "source_cells": 15, "cases": len(records)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

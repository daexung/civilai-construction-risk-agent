"""Connect exact area and region coefficient tables for 9-7-2."""
from __future__ import annotations
import json, sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.tools.calc.price import price_unit, select_rate_version
from pipeline.validate_drafts import file_sha256, load_chunks, validate_one


def main():
    path = ROOT / "data/drafts/specs/토목/9-7-2.json"
    package = json.loads(path.read_text(encoding="utf-8"))
    draft = package["draft"]
    base = next(t for t in draft["tables"] if t["id"] == "p583-t0")
    base["unit"] = "인/필지"
    trades = list(base["values"]["합계"])
    params = draft["quantity_model"]["params"]
    params["unit_rate_table"] = {
        "table": "p583-t0", "row_input": None, "column_input": None,
        "trades": trades, "trade_in_columns": True,
        "row_by_trade": {trade: "합계" for trade in trades},
        "basis_cites_by_row": {"합계": {
            "chunk_id": "p583-x10",
            "quote": "본 품은 1필지당 토지는 1,500㎡, 임야는 5,000㎡를 기준으로 하였으며, 기준면적 이하는 기준면적을 적용하고, 기준면적을 초과할 때에는 다음의 계수를 곱하여 계상한다."
        }}
    }
    params["quantity_input"] = "parcel_count"
    params["surcharges"] = []
    params["note_adjustments"] = []
    params["coefficient_combination"] = "multiply"
    params["coefficient_rules"] = [
        {"kind": "area_increment", "table": "p583-t1", "row": "계수",
         "area_input": "area", "land_input": "land_type",
         "base_area_by_value": {"토지": "1500", "임야": "5000"},
         "cite": {"chunk_id": "p583-x14",
                  "quote": "※ n은 가산횟수로 (대상면적-기준면적) ÷ 기준면적"}},
        {"table": "p583-t2", "row": "계수", "input": "region_type",
         "cite": {"chunk_id": "p583-x14",
                  "quote": "본 품은 면지역을 기준으로 하였으며, 행정구역이 다를 경우 다음의 계수를 곱하여 품을 계상한다."}}
    ]
    draft["quantity_model"]["steps"] = [
        "p583-t0 합계행의 직종별 품은 1필지 기준이다.",
        "토지는 1,500㎡, 임야는 5,000㎡ 기준으로 면적 가산횟수를 구하고 p583-t1에서 정확한 계수를 조회한다.",
        "지역구분계수를 p583-t2에서 조회한다.",
        "원문이 면적 및 지역 계수를 곱하여 계상하도록 명시하므로 두 계수를 기본 품에 곱한다.",
        "직종별 단위당 품에 대상 필지 수를 반영한다."
    ]
    for item in draft.get("not_calculated", []):
        text = {
            "기계경비 및 재료소모품비": "본 품에 사용되는 기계경비 및 재료소모품비는 별도 계상한다.",
            "지적측량기준점 설치비": "작업상 지적측량기준점을 설치할 경우에는 지적측량기준점 설치비를 별도 계상한다.",
            "선박 등 임차료 실비": "도서지역 등의 측량을 위하여 선박 등을 임차할 경우에는 임차료 실비를 별도 계상한다.",
            "국내여행자 일비 (여비)": "본 품의 외업에 필요한 여비는 공무원여비규정에 의한 국내여행자의 일비를 별도 계상한다."
        }.get(item.get("item"))
        if text:
            item["cite"] = {"chunk_id": "p584-x0", "quote": text}
    package["draft"] = draft
    path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    scenarios = [
        ({"parcel_count": "1", "land_type": "토지", "area": "1500", "region_type": "면"}, Fraction(1),
         ["0.52", "0.62", "0.27"]),
        ({"parcel_count": "1", "land_type": "토지", "area": "3000", "region_type": "읍"}, Fraction(143, 100),
         ["0.7436", "0.8866", "0.3861"]),
        ({"parcel_count": "2", "land_type": "임야", "area": "20000", "region_type": "동 구"}, Fraction(21, 10),
         ["1.092", "1.302", "0.567"])
    ]
    rates = [Fraction("0.52"), Fraction("0.62"), Fraction("0.27")]
    records = []
    for inputs, factor, printed in scenarios:
        result = per_unit(draft, inputs)
        assert result.get("status") == "computed", (inputs, result)
        actual = [Fraction(line["exact"]) for line in result["unit_lines"]]
        expected = [rate * factor for rate in rates]
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
    audit = {"section": "9-7-2", "physical_pages": [583], "printed_page": 527,
             "source_images": ["tmp/focus-583.png"], "source_cells_checked": 10,
             "scenarios": records,
             "scope": "Compared the original three base rates, all three area coefficient cells, four region coefficients and explicit 1-parcel/land-specific basis. Source states both coefficients multiply the work quantity. Exact rational cases check baseline, one increment and multi-increment area for 임야 with 동 구; offline price routing verified."}
    out = ROOT / "evals/runtime_validation/per-unit-9-7-2-area-region-product-audit-2026-10-19.json"
    out.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"section": "9-7-2", "focused_validation_ok": validation["ok"],
                      "source_cells": 10, "cases": len(records)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

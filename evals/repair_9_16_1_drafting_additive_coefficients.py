"""Connect 9-16-1 land, area and region coefficients to the per-unit runner."""
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
    path = ROOT / "data/drafts/specs/토목/9-16-1.json"
    package = json.loads(path.read_text(encoding="utf-8"))
    draft = package["draft"]
    table = next(t for t in draft["tables"] if t["id"] == "p612-t0")
    table["unit"] = "인/필지"
    trades = list(table["values"]["합계"])
    params = draft["quantity_model"]["params"]
    params["unit_rate_table"] = {
        "table": "p612-t0", "row_input": None, "column_input": None,
        "trades": trades, "trade_in_columns": True,
        "row_by_trade": {trade: "합계" for trade in trades},
        "basis_cites_by_row": {"합계": {
            "chunk_id": "p612-x10",
            "quote": "본 품은 1필지당 토지는 300㎡, 임야는 3,000㎡를 기준으로 하였으며, 기준면적 이하는 기준면적을 적용하고, 기준면적을 초과할 때에는 다음의 계수를 곱하여 계상한다."
        }}
    }
    params["quantity_input"] = "parcel_count"
    params["surcharges"] = []
    params["note_adjustments"] = []
    params["coefficient_combination"] = "additive_deltas"
    params["coefficient_rules"] = [
        {"kind": "area_increment", "table": "p612-t1", "row": "계수",
         "area_input": "area", "land_input": "land_type",
         "base_area_by_value": {"토지": "300", "임야": "3000"},
         "cite": {"chunk_id": "p612-x14",
                  "quote": "※ n은 가산횟수로 (대상면적-기준면적) ÷ 기준면적"}},
        {"table": "p612-t2", "row": "계수", "input": "land_type",
         "cite": {"chunk_id": "p612-x14",
                  "quote": "지적공부 등록지(토지, 임야) 별로 다음의 계수를 곱하여 계상한다."}},
        {"table": "p612-t3", "row": "계수", "input": "region_type",
         "cite": {"chunk_id": "p612-x17",
                  "quote": "본 품은 면지역을 기준으로 하였으며, 행정구역이 다를 경우 다음의 계수를 곱하여 품을 계상한다."}}
    ]
    draft["blocked"] = draft.get("blocked", []) + [{
        "condition": "request_appraisal == true",
        "blocked_if": {"input": "request_appraisal", "op": "==", "value": True},
        "reason": "추가 품 가산 가능 문구만 있고 추가 품 수치가 없어 계산 불가",
        "source": "PDF 557쪽 ⑥ 기타사항 ㉴",
        "cite": [{"chunk_id": "p613-x0",
                  "quote": "본 품의 측량결과에 대한 설명을 부가한 감정도 및 감정서 발급을 요청할 경우에는 추가 품을 가산 적용할 수 있다."}]
    }]
    draft["quantity_model"]["steps"] = [
        "p612-t0의 합계행에서 직종별 1필지 기본 품을 찾는다.",
        "토지 300㎡, 임야 3,000㎡ 기준으로 초과 가산횟수 n을 계산하고 p612-t1에서 면적계수를 조회한다.",
        "p612-t2의 등록계수와 p612-t3의 지역계수를 조회한다.",
        "원문 계산예대로 기본 1.00에 등록·지역·면적 계수 각각의 초과분(계수-1.00)을 더해 총 계수를 계산한다.",
        "직종별 기본 품에 총 계수와 필지 수를 반영한다. 추가 품 수치가 없는 감정도 요청은 계산을 차단한다."
    ]
    package["draft"] = draft
    path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    scenarios = [
        ({"parcel_count": "1", "land_type": "토지", "area": "1500",
          "region_type": "동 구", "request_appraisal": False}, Fraction(2),
         ["1.46", "1.54", "0.94"]),
        ({"parcel_count": "2", "land_type": "임야", "area": "3000",
          "region_type": "면", "request_appraisal": False}, Fraction(6, 5),
         ["0.876", "0.924", "0.564"]),
        ({"parcel_count": "1", "land_type": "토지", "area": "301",
          "region_type": "읍", "request_appraisal": False}, Fraction(7, 5),
         ["1.022", "1.078", "0.658"]),
        ({"parcel_count": "1", "land_type": "토지", "area": "1500",
          "region_type": "동 구", "request_appraisal": True}, None, None)
    ]
    rates = [Fraction("0.73"), Fraction("0.77"), Fraction("0.47")]
    records = []
    for inputs, factor, printed in scenarios:
        result = per_unit(draft, inputs)
        if inputs["request_appraisal"]:
            assert result.get("status") == "blocked", result
            records.append({"inputs": inputs, "status": result["status"],
                            "reason": result.get("reason")})
            continue
        assert result.get("status") == "computed", result
        expected = [x * factor for x in rates]
        actual = [Fraction(line["exact"]) for line in result["unit_lines"]]
        assert actual == expected == [Fraction(x) for x in printed], (inputs, actual, printed)
        priced = price_unit(draft, result["unit_lines"], select_rate_version("2026-10-01"),
                            inputs, "2026-10-01")
        assert priced.get("status") in ("COMPLETE", "PARTIAL"), priced
        records.append({"inputs": inputs, "status": result["status"],
                        "independent_expected": [str(x) for x in expected],
                        "unit_lines": result["unit_lines"],
                        "offline_price_status": priced["status"]})

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
    audit = {
        "section": "9-16-1", "physical_pages": [612, 613],
        "source_images": ["tmp/focus-612.png", "tmp/focus-613.png"],
        "source_cells_checked": 12, "scenarios": records,
        "scope": "Visually compared p612 base rates (0.73/0.77/0.47), land-specific area bases (300/3,000㎡), all three area coefficient cells, two registration cells, four region cells, and p613 printed example (1.00+0.00+0.40+0.60=2.00; outputs 1.46/1.54/0.94). Also checked an 임야 base case, one increment, offline price routing and blocked unspecified appraisal addition."
    }
    out = ROOT / "evals/runtime_validation/per-unit-9-16-1-additive-coefficient-audit-2026-10-19.json"
    out.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"section": "9-16-1", "focused_validation_ok": validation["ok"],
                      "source_cells": 12, "cases": len(records)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

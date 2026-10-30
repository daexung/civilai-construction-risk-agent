"""Connect 9-16-2 source tables and the printed additive-coefficient example."""
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
    path = ROOT / "data/drafts/specs/토목/9-16-2.json"
    package = json.loads(path.read_text(encoding="utf-8"))
    draft = package["draft"]
    if not any(x["name"] == "parcel_count" for x in draft["inputs"]):
        draft["inputs"].append({
            "name": "parcel_count", "type": "positive_rational",
            "allowed_values": "1 이상의 정수", "unit": "필지", "required": True,
            "ask": "대상 필지는 몇 필지입니까?",
            "source": "PDF 2쪽 ② 면적계수 및 1쪽 직종별 기본 품 표의 1필지 기준"
        })
    count_field = next(x for x in draft["inputs"] if x["name"] == "parcel_count")
    count_field.update({"type": "positive_rational", "allowed_values": "0보다 큰 수",
                        "unit": "필지", "required": True})
    params = draft["quantity_model"]["params"]
    params["unit_rate_table"] = {
        "table": "p613-t1", "row_input": None, "column_input": None,
        "trades": ["지적기사", "지적산업기사", "지적기능사"],
        "trade_in_columns": True,
        "row_by_trade": {trade: "합계" for trade in
                         ("지적기사", "지적산업기사", "지적기능사")},
        "basis_cites_by_row": {"합계": {
            "chunk_id": "p614-x0",
            "quote": "본 품은 1필지당 300㎡를 기준으로 하였으며, 기준면적 이하는 기준면적을 적용하고, 기준면적을 초과할 때에는 다음의 계수를 곱하여 계상한다."
        }}
    }
    params["quantity_input"] = "parcel_count"
    params["note_adjustments"] = []
    params["coefficient_combination"] = "additive_deltas"
    params["coefficient_rules"] = [
        {"kind": "area_increment", "table": "p614-t0", "row": "계수",
         "area_input": "area", "base_area": "300",
         "cite": {"chunk_id": "p614-x4",
                  "quote": "※ n은 가산횟수로 (대상면적-기준면적) ÷ 기준면적"}},
        {"table": "p614-t1", "row": "계수", "input": "region_type",
         "cite": {"chunk_id": "p614-x4",
                  "quote": "본 품은 면지역을 기준으로 하였으며, 행정구역이 다를 경우 다음의 계수를 곱하여 품을 계상한다."}}
    ]
    draft["quantity_model"]["steps"] = [
        "p613-t1의 합계행에서 직종별 1필지 기본 품을 찾는다.",
        "기준면적 300㎡를 초과하면 n=ceil((면적-기준면적)/기준면적)으로 가산횟수를 산정하고 p614-t0의 정확한 계수를 조회한다.",
        "면 지역은 기준계수 1.00, 그 밖의 지역은 p614-t1의 지역계수를 적용한다.",
        "원문 계산예에 따라 총 계수는 1.00 + 등록계수 0.00 + (지역계수-1.00) + (면적계수-1.00)으로 산정한다.",
        "직종별 기본 품에 총 계수와 필지 수를 반영한다. 감정도·감정서 요청 시 추가 품 수치가 없어 계산을 차단한다."
    ]
    package["draft"] = draft
    path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    scenarios = [
        ({"area": "1500", "region_type": "동 구", "appraisal_requested": False,
          "parcel_count": "1"}, Fraction(2), ["1.16", "1.24", "0.68"]),
        ({"area": "300", "region_type": "면", "appraisal_requested": False,
          "parcel_count": "2"}, Fraction(1), ["0.58", "0.62", "0.34"]),
        ({"area": "301", "region_type": "읍", "appraisal_requested": False,
          "parcel_count": "1"}, Fraction(14, 10), ["0.812", "0.868", "0.476"]),
        ({"area": "1500", "region_type": "동 구", "appraisal_requested": True,
          "parcel_count": "1"}, None, None),
    ]
    records = []
    rates = [Fraction("0.58"), Fraction("0.62"), Fraction("0.34")]
    for inputs, expected_factor, printed in scenarios:
        result = per_unit(draft, inputs)
        if inputs["appraisal_requested"]:
            assert result.get("status") == "blocked", result
            records.append({"inputs": inputs, "status": result["status"],
                            "reason": result.get("reason")})
            continue
        assert result.get("status") == "computed", result
        expected = [x * expected_factor for x in rates]
        actual = [Fraction(line["exact"]) for line in result["unit_lines"]]
        assert actual == expected and actual == [Fraction(x) for x in printed], (inputs, actual, printed)
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
        "section": "9-16-2", "physical_pages": [613, 614],
        "source_images": ["tmp/9-16-source-p613.png", "tmp/9-16-source-p614.png"],
        "source_cells_checked": 10, "scenarios": records,
        "scope": "Independently compared three p613-t1 labor cells, three p614-t0 area coefficient cells and four p614-t1 region coefficient cells. The printed source example gives 1.00 + 0.00 + 0.40 + 0.60 = 2.00 and rates 1.16/1.24/0.68, confirming additive deltas. Checked threshold/base, source worked example, one-area increment, offline price routing, and blocked unspecified appraisal addition."
    }
    out = ROOT / "evals/runtime_validation/per-unit-9-16-2-additive-coefficient-audit-2026-10-19.json"
    out.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"section": "9-16-2", "focused_validation_ok": validation["ok"],
                      "source_cells": 10, "cases": len(records),
                      "computed_cases": sum(r["status"] == "computed" for r in records),
                      "blocked_cases": sum(r["status"] == "blocked" for r in records)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

"""Connect the printed additive coefficient rule for 9-8-1."""
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
    path = ROOT / "data/drafts/specs/토목/9-8-1.json"
    package = json.loads(path.read_text(encoding="utf-8"))
    draft = package["draft"]
    table = next(t for t in draft["tables"] if t["id"] == "p587-t0")
    table["unit"] = "인·일/필지"
    trades = list(table["values"]["합계"])
    params = draft["quantity_model"]["params"]
    params["unit_rate_table"] = {
        "table": "p587-t0", "row_input": None, "column_input": None,
        "trades": trades, "trade_in_columns": True,
        "row_by_trade": {trade: "합계" for trade in trades},
        "basis_cites_by_row": {"합계": {
            "chunk_id": "p587-x13",
            "quote": "본 품은 1필지당 1,500㎡를 기준으로 하였으며, 기준면적 이하는 기준면적을 적용하고 기준면적을 초과할 때에는 다음의 계수를 곱하여 계상한다."
        }}
    }
    params["quantity_input"] = "parcel_count"
    params["surcharges"] = []
    params["note_adjustments"] = []
    params["coefficient_combination"] = "additive_deltas"
    params["coefficient_rules"] = [
        {"kind": "area_increment", "table": "p587-t1", "row": "계수",
         "area_input": "area_per_parcel", "base_area": "1500",
         "cite": {"chunk_id": "p587-x17",
                  "quote": "※ n은 가산횟수로 (대상면적-기준면적)÷기준면적"}},
        {"table": "p588-t0", "row": "계수", "input": "region",
         "cite": {"chunk_id": "p588-x0",
                  "quote": "본 품은 면지역을 기준으로 하였으며, 행정구역이 다를 경우 다음의 계수를 곱하여 품을 계상한다."}}
    ]
    draft["quantity_model"]["steps"] = [
        "p587-t0에서 직종별 1필지 기본 품을 조회한다.",
        "1,500㎡ 기준으로 면적 가산횟수 n을 계산해 p587-t1의 정확한 계수를 적용한다.",
        "행정구역별 계수를 p588-t0에서 조회한다.",
        "원문 계산예에 따라 기본 1.00에 면적계수와 지역계수의 초과분을 각각 더해 총 계수를 구한다.",
        "직종별 단위당 품에 필지 수를 곱한다."
    ]
    package["draft"] = draft
    path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    scenarios = [
        ({"parcel_count": "1", "area_per_parcel": "7000", "region": "동 구"}, Fraction(2),
         ["1.52", "1.62", "0.92"]),
        ({"parcel_count": "2", "area_per_parcel": "1500", "region": "면"}, Fraction(1),
         ["0.76", "0.81", "0.46"]),
        ({"parcel_count": "1", "area_per_parcel": "1501", "region": "읍"}, Fraction(7, 5),
         ["1.064", "1.134", "0.644"])
    ]
    rates = [Fraction("0.76"), Fraction("0.81"), Fraction("0.46")]
    records = []
    for inputs, factor, printed in scenarios:
        result = per_unit(draft, inputs)
        assert result.get("status") == "computed", (inputs, result)
        actual = [Fraction(line["exact"]) for line in result["unit_lines"]]
        expected = [x * factor for x in rates]
        assert actual == expected == [Fraction(x) for x in printed], (inputs, actual, printed)
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
    out = ROOT / "evals/runtime_validation/per-unit-9-8-1-additive-coefficient-audit-2026-10-19.json"
    out.write_text(json.dumps({
        "section": "9-8-1", "physical_pages": [587, 588],
        "source_images": ["tmp/focus-587.png", "tmp/focus-588.png"],
        "source_cells_checked": 10, "scenarios": records,
        "scope": "Compared three p587-t0 base rates, three p587-t1 area coefficient cells, and four p588-t0 region coefficient cells against original PDF. Printed example: 7,000㎡ forest parcel converted to land in 구지역, factor 2.00, outputs 1.52/1.62/0.92. Also checked the 1,500㎡ threshold, one-increment route, and offline prices."
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"section": "9-8-1", "focused_validation_ok": validation["ok"],
                      "source_cells": 10, "cases": len(records)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

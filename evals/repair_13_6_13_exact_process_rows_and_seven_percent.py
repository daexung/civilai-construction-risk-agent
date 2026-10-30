"""Route every Tainter Gate manufacturing cell and its source 7% rule."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data/drafts/specs/기계설비/13-6-13.json"
EXPECTED = {
    "기술관리": {"기계기사": "8.0"}, "재료절단사도": {"제도공": "2.0"},
    "현도": {"현도공": "1.4"}, "괘서": {"마킹공": "2.8"},
    "재료절단": {"절단공": "0.52"}, "단재가공괘서": {"마킹공": "2.8"},
    "절단": {"산소절단공": "0.26", "플랜트기계설치공": "2.3"},
    "Edge": {"산소절단공": "1.1"}, "용접": {"플랜트용접공": "0.78"},
    "교정": {"플랜트제관공": "0.75"}, "Holing": {"플랜트제관공": "0.62"},
    "부분조립취부조정": {"플랜트기계설치공": "6.2"}, "용접 ": {"플랜트용접공": "3.9"},
    "교정 ": {"플랜트제관공": "1.75"}, "기계가공": {"기계설비공": "10"},
    "가조립조립": {"플랜트기계설치공": "2.0"}, "해체": {"플랜트기계설치공": "1.0"},
    "운반조작": {"특수비계공": "5.0"}, "동력조작": {"플랜트전공": "2.0"},
    "보조": {"특별인부": "2.5"},
}
NOTE_ROW, NOTE_COLUMN = "검사", "인력품의 7%"

def main():
    package = json.loads(PATH.read_text(encoding="utf-8"))
    draft = package["draft"]
    table = next(t for t in draft["tables"] if t["id"] == "p873-t1")
    values = table["values"]
    actual_rates = {row: cells for row, cells in values.items() if row != NOTE_ROW}
    assert actual_rates == EXPECTED, (actual_rates, EXPECTED)
    values[NOTE_ROW] = {NOTE_COLUMN: ""}

    params = draft["quantity_model"]["params"]
    params["quantity_input"] = "quantity"
    params["unit_rate_table"] = {
        "table": "p873-t1", "row_input": None, "column_input": None,
        "trades": ["기계기사"], "row_by_trade": {"기계기사": "기술관리"},
        "resource_units": {},
    }
    params["additional_unit_rates"] = [
        {"table": "p873-t1", "row_by_trade": {trade: row},
         "column_by_trade": {trade: trade}, "trades": [trade],
         "quantity_input": "quantity", "basis_by_trade": {trade: "인/ton"}}
        for row, cells in EXPECTED.items() for trade in cells
        if not (row == "기술관리" and trade == "기계기사")
    ]
    params["input_rate_adjustments"] = [{
        "operation": "add_source_percent", "name": "검사", "percent": "7",
        "kinds": ["labor"],
        "cite": {"table_id": "p873-t1", "row": NOTE_ROW, "column": NOTE_COLUMN},
    }]
    draft["quantity_model"]["steps"] = [
        "Tainter Gate Guide Metal 제작의 각 공정별 원문 행과 직종 셀의 인/ton 품을 합산한다.",
        "원문 검사 행의 인력품의 7%를 모든 공정 인력품에 가산한다.",
        "합산한 ton당 품에 제작 ton 물량을 곱한다.",
    ]
    PATH.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"source_rows": len(EXPECTED), "numeric_source_cells": sum(map(len, EXPECTED.values())),
                      "additional_exact_cells": sum(map(len, EXPECTED.values())) - 1,
                      "source_adjustment": "7% of all labor lines"}, ensure_ascii=False))

if __name__ == "__main__":
    main()

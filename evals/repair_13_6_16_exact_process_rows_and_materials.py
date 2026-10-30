"""Reconstruct flattened Trash Rack source rows and exact labor/material routes."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data/drafts/specs/기계설비/13-6-16.json"
LABOR = {
    "기술관리": {"기계기사": "1.66"},
    "운반검측": {"플랜트기계설치공": "0.05", "특별인부": "0.05"},
    "수정": {"산소절단공": "0.05", "플랜트기계설치공": "0.05", "특별인부": "0.10"},
    "설치준비철근정리": {"산소절단공": "0.047", "특별인부": "0.047"},
    "Chipping": {"석공": "0.1", "특별인부": "0.05"},
    "Beam 설치": {"특별인부": "0.175"},
    "Crane 작업": {"특수비계공": "0.18"},
    "Beam 설치 crane 작업": {"측량사": "0.14"},
    "1차 센터링": {"측량조수": "0.14", "특수비계공": "0.14", "특별인부": "0.28", "플랜트기계설치공": "0.14"},
    "턴버클 용접": {"플랜트용접공": "0.21", "특별인부": "0.21"},
    "Beam 완전 고정": {"산소절단공": "0.015", "플랜트용접공": "2.7", "특별인부": "2.7"},
    "Trash Rack 설치": {"특별인부": "0.67"},
    "1차 조립": {"특수비계공": "0.59", "플랜트기계설치공": "0.45"},
    "2차 센터링": {"측량사": "0.087", "측량조수": "0.087", "플랜트기계설치공": "0.087", "특별인부": "0.166", "플랜트용접공": "0.79"},
    "검사": {"플랜트기계설치공": "0.035", "특별인부": "0.035"},
    "도장준비": {"플랜트제관공": "2.98"},
    "도장": {"도장공": "2.98"},
    "강재거푸집철거": {"플랜트용접공": "0.017", "특별인부": "0.017"},
    "뒷정리": {"플랜트기계설치공": "0.035", "산소절단공": "0.017", "특별인부": "0.35"},
    "전원조작": {"플랜트전공": "0.52", "특별인부": "0.52"},
}
MATERIALS = {
    "수정·절단": {"산소": "0.029"},
    "용접": {"아세틸렌": "0.012", "용접봉": "5.95"},
    "도장": {"Tar Epoxy": "7.06", "시너": "1.58"},
}
MATERIAL_UNITS = {"산소": ("병", "병/ton"), "아세틸렌": ("병", "병/ton"),
                  "용접봉": ("kg", "kg/ton"), "Tar Epoxy": ("ℓ", "ℓ/ton"),
                  "시너": ("ℓ", "ℓ/ton")}

def main():
    package = json.loads(PATH.read_text(encoding="utf-8"))
    draft = package["draft"]
    tables = {t["id"]: t for t in draft["tables"]}
    tables["p876-t2"]["values"] = LABOR
    tables["p877-t0"]["values"] = dict(list(LABOR.items())[8:])
    tables["p876-t2"]["values"] = dict(list(LABOR.items())[:8])
    tables["p877-t1"]["values"] = MATERIALS
    params = draft["quantity_model"]["params"]
    params["quantity_input"] = "quantity"
    first_row, first_trade = next(iter(LABOR.items()))
    first_trade = next(iter(first_trade))
    params["unit_rate_table"] = {
        "table": "p876-t2", "row_input": None, "column_input": None,
        "trades": [first_trade], "row_by_trade": {first_trade: first_row},
    }
    rates = []
    for page_index, (row, cells) in enumerate(LABOR.items()):
        table_id = "p876-t2" if page_index < 8 else "p877-t0"
        for trade in cells:
            if table_id == "p876-t2" and row == first_row and trade == first_trade:
                continue
            rates.append({"table": table_id, "row_by_trade": {trade: row},
                          "column_by_trade": {trade: trade}, "trades": [trade],
                          "quantity_input": "quantity", "basis_by_trade": {trade: "인/ton"}})
    params["additional_unit_rates"] = rates
    params["additional_materials"] = [
        {"table": "p877-t1", "row": row, "column": name, "name": name,
         "unit": MATERIAL_UNITS[name][0], "basis": MATERIAL_UNITS[name][1],
         "quantity_input": "quantity",
         **({"cite": {"chunk_id": "p877-x34",
                       "quote": "※ 산소량 규격은 대기압상태를 기준하며, 단위 ‘병’은 35℃에서 150기압으로 압축용기에 넣어 사용하는 것을 기준한다."}}
            if name in ("산소", "아세틸렌") else {})}
        for row, cells in MATERIALS.items() for name in cells
    ]
    draft["quantity_model"]["steps"] = [
        "각 공정별 p.820~821 인/ton 원문 행의 모든 직종 품을 연결한다.",
        "각 공정별 소모자재 원문량을 해당 품명과 단위(병·kg·ℓ) 그대로 ton당 자재량으로 산출한다.",
        "단위당 인력 및 자재 산출량에 Trash Rack 설치 ton 물량을 곱한다.",
        "산소·아세틸렌 병 수량은 원문 주석의 35℃, 150기압 압축용기 기준이다.",
    ]
    PATH.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"labor_rows": len(LABOR), "labor_cells": sum(map(len, LABOR.values())),
                      "materials": sum(map(len, MATERIALS.values())),
                      "additional_labor_routes": len(rates)}, ensure_ascii=False))

if __name__ == "__main__":
    main()

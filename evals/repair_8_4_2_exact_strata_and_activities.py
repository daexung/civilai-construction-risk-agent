"""Connect the four source matrices and conditional activity quantities exactly."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "data/drafts/specs/토목/8-4-2.json"

TABLES = {
    "풍화암": "p459-t1", "연암": "p459-t2",
    "보통암": "p460-t0", "경암": "p460-t1",
}
LABOR_COLUMNS = {
    "중급기술자": "인력품 중급\n기술자",
    "중급숙련기술자": "인력품 중급숙련\n기술자",
    "보링공": "인력품 보링공",
    "특별인부": "인력품 특별\n인부",
    "보통인부": "인력품 보통\n인부",
}
ACTIVITIES = {
    "케이싱설치": ("m", "m", "additional_work_quantity_casing"),
    "에어써징": ("m", "m", "additional_work_quantity_air_surge"),
    "우물설치": ("m", "m", "additional_work_quantity_well"),
    "양수시험": ("시간", "1/시간", "additional_work_quantity_pumping"),
}


def main() -> None:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    tables = {table["id"]: table for table in spec["tables"]}
    source_trades = {key: list(tables[table_id]["values"])
                     for key, table_id in TABLES.items()}
    assert all(len(tables[table_id]["values"]) == len(source_trades[rock])
               for rock, table_id in TABLES.items())

    quantity_fields = []
    for activity, (unit, basis, input_name) in ACTIVITIES.items():
        quantity_fields.append({
            "name": input_name, "type": "positive_rational", "allowed_values": "0보다 큰 수",
            "unit": unit, "required": True,
            "ask": f"{activity} 물량은 몇 {unit}입니까?",
            "source": f"PDF 404쪽 [주] ② p460-t2의 {activity} 단위",
            "when": {"input": "additional_work", "equals": activity},
        })
    spec["inputs"] = [field for field in spec["inputs"]
                      if field["name"] != "additional_work_quantity"] + quantity_fields

    rate = spec["quantity_model"]["params"]["unit_rate_table"]
    rate["table_selector"] = {
        "routes": [{"when": {"rock_type": rock}, "table": table_id}
                   for rock, table_id in TABLES.items()]
    }
    rate["row_input"] = None
    rate["column_input"] = {
        "input": "diameter", "exact_input_contains": ["diameter"],
        "input_contains": ["rock_type"], "exact_component_inputs": ["rock_type"],
    }
    rate["trades_by_table"] = source_trades
    rate["resource_kinds"] = {
        "중급기술자": "labor", "중급숙련기술자": "labor", "보링공": "labor",
        "특별인부": "labor", "보통인부": "labor", "고성능착정기": "equipment",
        "윙비트": "material", "벤토나이트": "material", "기포제": "material",
        "에어해머": "material", "버튼(Button)비트": "material",
    }
    rate["resource_units"] = {
        "중급기술자": "인", "중급숙련기술자": "인", "보링공": "인",
        "특별인부": "인", "보통인부": "인", "고성능착정기": "hr",
        "윙비트": "개", "벤토나이트": "kg", "기포제": "ℓ",
        "에어해머": "개", "버튼(Button)비트": "개",
    }
    additions = []
    activity_table = tables["p460-t2"]
    for activity, (source_unit, basis, quantity_name) in ACTIVITIES.items():
        row = activity_table["values"][activity]
        assert row["단위"] == source_unit
        for trade, column in LABOR_COLUMNS.items():
            assert column in row and row[column].strip()
            additions.append({
                "table": "p460-t2", "basis": basis, "quantity_input": quantity_name,
                "trades": [trade], "row_by_trade": {trade: activity}, "column": column,
                "when": {"additional_work": activity},
                "source": f"PDF 404쪽 [주] ② {activity} 행 / {trade} 열",
            })
    spec["quantity_model"]["params"]["additional_unit_rates"] = additions
    spec["quantity_model"]["params"]["note_adjustments"] = []
    spec["quantity_model"]["steps"] = [
        "암종(rock_type)에 해당하는 p459-t1, p459-t2, p460-t0, p460-t1 표를 선택한다.",
        "표에서 직종·장비·재료 행과 암종·직경 열을 정확히 조회한다.",
        "단위당 품에 천공 길이(quantity)를 곱한다.",
        "추가 작업이 있으면 p460-t2의 해당 작업 행과 직종 열을 조회하고, 원문 단위(m 또는 시간)의 해당 물량을 곱해 노무량에 더한다.",
        "장비경비는 원문의 별도 계상 지시를 따른다.",
    ]
    package["open_questions"] = [
        "윙비트·벤토나이트·기포제·에어해머·버튼비트의 물량은 계산하나 재료 단가 자료가 없어 금액은 미산정합니다.",
        "추가 작업 표는 원문 지시대로 인력만 산출합니다. 장비 경비는 별도 계상입니다.",
    ]
    SPEC.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"id": spec["id"], "primary_tables": TABLES,
                      "resource_rows": {key: len(value) for key, value in source_trades.items()},
                      "activity_trade_routes": len(additions)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

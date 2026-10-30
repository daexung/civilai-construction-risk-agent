"""Represent the source-defined denominator for every construction-water row."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "data/drafts/specs/공통/1-5-6.json"

UNITS = {
    "거푸집씻기": "㎡", "콘크리트혼합및양생": "㎥", "경량콘크리트혼합및양생": "㎥",
    "보통벽돌쌓기": "매", "돌쌓기모르타르": "㎡", "돌씻기": "㎡", "미장": "㎡",
    "타일붙임모르타르": "㎡", "타일씻기": "㎡", "잡용수": "㎥",
}
RATE_UNITS = {
    "거푸집씻기": "㎥/㎡", "콘크리트혼합및양생": "㎥/㎥", "경량콘크리트혼합및양생": "㎥/㎥",
    "보통벽돌쌓기": "㎥/1,000매", "돌쌓기모르타르": "㎥/㎡", "돌씻기": "㎥/㎡",
    "미장": "㎥/㎡", "타일붙임모르타르": "㎥/㎡", "타일씻기": "㎥/㎡", "잡용수": "㎥",
}

def main() -> None:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    draft = package["draft"]
    table = next(t for t in draft["tables"] if t["id"] == "p89-t0")
    old_values = table["values"]["수량"]
    assert set(old_values) == set(UNITS)
    table["values"] = {
        work_type: {"수량": raw}
        for work_type, raw in old_values.items()
    }
    for field in draft["inputs"]:
        if field["name"] == "quantity":
            field["unit"] = "㎡/㎥/매 (공종별 원문 단위)"
            field["unit_by"] = {"input": "work_type", "values": UNITS}
    draft["quantity_model"]["name"] = "per_unit"
    params = draft["quantity_model"]["params"]
    params["unit_rate_table"] = {
        "table": "p89-t0", "row_input": "work_type", "column_input": "수량",
        "trades": ["수량"], "resource_units": {"수량": "㎥"},
        "resource_kinds": {"수량": "material"},
        "basis_by_row": RATE_UNITS,
        "quantity_unit_selector": {"input": "work_type", "values": UNITS},
    }
    params["quantity_input"] = "quantity"
    draft["quantity_model"]["steps"] = [
        "원문 표에서 공종(work_type)에 해당하는 단위(분모)와 수량 계수를 선택한다.",
        "각 공종의 물량 단위를 원문 분모와 맞춘 뒤 계수를 곱하여 공사용수(㎥)를 산출한다.",
        "잡용수는 원문에 사용량비 40~50%만 제시되어 기준량과 적용률이 확정되지 않으므로 자동 계산을 보류한다.",
    ]
    draft["blocked"] = [{
        "condition": "잡용수의 사용량비 기준량 및 40~50% 범위 내 적용률이 확정되지 않음",
        "blocked_if": {"input": "work_type", "op": "==", "value": "잡용수"},
        "reason": "원문 범위에서 값을 임의 선택하지 않음",
        "source": "PDF 33쪽 3. 공사용수 표",
        "cite": {"table_id": "p89-t0", "row": "잡용수", "column": "수량", "value": "사용량비의 40∼50%"},
    }]
    draft["open_questions"] = ["잡용수의 40~50% 범위 내 적용률과 사용량비 기준량은 원문에서 특정되지 않는다."]
    draft["questions"] = []
    package["citations"] = [
        {"table_id": "p89-t0", "row": work_type, "column": "수량", "value": raw}
        for work_type, cells in table["values"].items() for raw in cells.values()
    ]
    package["calc_type"] = "per_unit"
    package["calc_type_raw"] = "per_unit"
    package["calc_type_reason"] = "원문 표를 공종 행과 단일 수량 열로 재구성하고 모든 공종의 분모 단위를 출처대로 연결; 잡용수 범위 요율은 차단"
    SPEC.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("reconstructed 10 source rows; mapped nine exact quantity bases and retained the 40-50% source range as blocked")

if __name__ == "__main__":
    main()

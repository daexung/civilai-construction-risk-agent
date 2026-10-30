"""Route the two source tables by weight and exact height cells for maintenance 1-3-8."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data/drafts/specs/유지관리/1-3-8.json"
package = json.loads(PATH.read_text(encoding="utf-8"))
draft = package["draft"]
table_for_weight = {
    "0.2ton 이하": "p926-t0", "0.3ton 이하": "p926-t0", "0.5ton 이하": "p926-t0",
    "1.0ton 이하": "p926-t1", "1.5ton 이하": "p926-t1", "1.5ton 초과": "p926-t1",
}
tables = {item["id"]: item for item in draft["tables"]}
for table_id in ("p926-t0", "p926-t1"):
    tables[table_id]["source"] = "PDF 870쪽 1-3-8 교량받침 교체 일당표"
draft["quantity_model"] = {
    "name": "adjusted_daily_crew",
    "params": {
        "base_output": {"table": "p926-t0", "table_selector": {
            "input": "bearing_weight", "values": table_for_weight},
            "row_input": "bearing_weight", "column_input": "pier_height"},
        "coefficients": [],
        "crew": {"table": "p926-t0", "table_selector": {
            "input": "bearing_weight", "values": table_for_weight},
            "row_input": "bearing_weight", "trades": ["특별인부", "보통인부", "용접공"],
            "column_selector_by_trade": {trade: trade for trade in ["특별인부", "보통인부", "용접공"]}},
        "equipment": [
            {"table": "p926-t0", "table_selector": {"input": "bearing_weight", "values": table_for_weight},
             "name": equipment, "row_selector": "bearing_weight", "column": equipment, "unit": "대·일",
             **({"when": {"scaffold_installed": False}, "cite": {"chunk_id": "p927-x0",
                  "quote": "교대 및 교각 전체에 비계 및 작업발판을 설치한 경우에는 고소작업차의 투입을 제외한다."}}
                 if equipment == "고소작업차" else {})}
            for equipment in ["크레인", "고소작업차"]
        ],
        "quantity_input": "quantity",
    },
    "steps": [
        "교량받침 중량에 따라 p926-t0(0.5ton 이하) 또는 p926-t1(1.0ton 이하 이상)의 원문표를 선택한다.",
        "선택된 중량 행과 교대·교각높이 열의 교차 셀에서 일일시공량(개)을 읽는다.",
        "같은 중량 행의 특별인부·보통인부·용접공, 크레인, 고소작업차 기준 수량을 읽는다.",
        "교대 및 교각 전체에 비계와 작업발판을 설치한 경우 고소작업차는 투입하지 않는다(871쪽 주 ③).",
        "작업일수 = 교체수량 ÷ 원문 일일시공량; 직종 인·일 및 장비 대·일 = 작업일수 × 표 수량.",
        "상부 인상/인하, 코핑부 보강 및 비계 설치는 별도 계상으로 이 모델에서 계산하지 않는다.",
    ],
    "source": "PDF 870~871쪽 1-3-8 교량받침 교체 표와 주 ③",
    "rounding": "총 투입량은 정확한 유리수로 보존; 단위당 품은 공통 1-2-8·1-2-1 기본 자릿수 적용",
}
draft["crew_rules"] = []
draft["blocked"] = []
draft["calc_type_reason"] = "PDF 870쪽 두 표는 중량 범위별로 나뉘며 각 행에 일일시공량, 높이별 열, 작업조 및 장비 수량이 명시되어 있다. 중량으로 표를 고르고 행·열을 정확히 조회하는 adjusted_daily_crew 경로에 연결했다. 주 ③은 설치 비계 여부에 따른 고소작업차 제외로 반영했다."
draft["open_questions"] = []
package["open_questions"] = []
package["calc_type"] = "daily_crew"
PATH.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("reconstructed", draft["id"])

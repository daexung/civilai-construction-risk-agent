"""Connect the source-confirmed type-specific daily crew in maintenance 2-1-10."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data/drafts/specs/유지관리/2-1-10.json"
package = json.loads(PATH.read_text(encoding="utf-8"))
draft = package["draft"]
type_values = {"A Type": "A-Type", "B Type": "B-Type", "C Type": "C-Type"}
table = next(item for item in draft["tables"] if item["id"] == "p935-t2")
rows = table["values"]
output_row = {f"{kind} 시공량(㎡)": rows["포장공"][f"{kind} 시공량(㎡)"]
              for kind in type_values.values()}
rows["시공량"] = output_row
for kind in type_values.values():
    rows["포장공"].pop(f"{kind} 시공량(㎡)")
table["source"] = "PDF 879쪽 2-1-10 (일당) 표; 포장공 행의 시공량 셀을 분리"
for table_id, label in (("p936-t0", "A-Type"), ("p936-t1", "B-Type"), ("p936-t2", "C-Type")):
    next(item for item in draft["tables"] if item["id"] == table_id)["source"] = (
        f"PDF 880쪽 2-1-10 ⑤ {label} 시공량 할증계수 표")
draft["quantity_model"] = {
    "name": "adjusted_daily_crew",
    "params": {
        "base_output": {"table": "p935-t2", "row": "시공량",
                        "column_selector": {"input": "site_type", "contains": ["{value} 시공량(㎡)"],
                                            "value_map": type_values}},
        "coefficients": [{"table": "p936-t0", "table_selector": {
            "input": "site_type", "values": {"A Type": "p936-t0", "B Type": "p936-t1", "C Type": "p936-t2"}},
            "row": "시공량 할증계수", "input": "area_per_location", "selector_mode": "threshold"}],
        "crew": {"table": "p935-t2", "trades": ["포장공", "보통인부"],
                 "column_selector": {"input": "site_type", "contains": ["{value} 수량"],
                                     "value_map": type_values}},
        "equipment": [
            {"table": "p935-t2", "name": row, "row": row,
             "column": f"{type_values[site_type]} 수량", "unit": "대·일", "when": {"site_type": site_type}}
            for site_type, equipment_rows in {
                "A Type": ["굴착기+대형브레이커", "로더(타이어)", "커터(콘크리트 및 아스팔트용)",
                           "진동롤러(진동+타이어)", "아스팔트스프레이어", "트럭"],
                "B Type": ["굴착기+대형브레이커", "로더(타이어)", "커터(콘크리트 및 아스팔트용)",
                           "진동롤러(진동+타이어)", "아스팔트스프레이어", "트럭"],
                "C Type": ["굴착기+대형브레이커", "로더(타이어)", "커터(콘크리트 및 아스팔트용)",
                           "진동롤러(핸드가이드식)", "플레이트콤팩터", "아스팔트스프레이어", "트럭"],
            }.items() for row in equipment_rows
        ],
        "quantity_input": "total_area",
    },
    "steps": [
        "p935-t4 현장 여건별 적용기준에 따라 A/B/C Type을 정한다.",
        "p935-t2에서 선택한 Type의 기준 일당시공량, 인원 및 장비 대수를 확인한다.",
        "개소별 평균면적에 따라 p936-t0(A), p936-t1(B) 또는 p936-t2(C)의 원문 구간을 선택한다.",
        "보정 일당시공량 = 기준 일당시공량 × 원문 시공량 할증계수로 계산한다.",
        "작업일수 = 총 시공면적 ÷ 보정 일당시공량으로 계산하고 직종 인·일과 장비 대·일을 산출한다.",
    ],
    "source": "PDF 879~880쪽 2-1-10 소파보수(도로복구) 표 및 ④~⑥ 주",
    "rounding": "총 투입량은 정확한 유리수로 보존; 단위당 품은 공통 1-2-8·1-2-1 기본 자릿수 적용",
}
draft["blocked"] = []
draft["open_questions"] = []
draft["calc_type_reason"] = "A/B/C별 작업조·장비·기준시공량 및 평균면적 할증표가 PDF 879~880쪽에 명시되어 있으며, Type별 원문표를 구간 선택해 일당 작업조 계산에 연결했다."
package["open_questions"] = []
package["calc_type"] = "daily_crew"
PATH.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("reconstructed", draft["id"])

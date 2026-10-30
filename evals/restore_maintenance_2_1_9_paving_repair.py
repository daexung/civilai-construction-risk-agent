"""Reconstruct maintenance 2-1-9 rows and connect the confirmed daily crew rules."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data/drafts/specs/유지관리/2-1-9.json"
package = json.loads(PATH.read_text(encoding="utf-8"))
draft = package["draft"]
table = next(item for item in draft["tables"] if item["id"] == "p934-t1")
table["values"] = {
    "시공량": {
        "A-Type 시공량(㎡)": "110", "B-Type 시공량(㎡)": "45", "C-Type 시공량(㎡)": "20",
    },
    "포장공": {"A-Type 수량": "3", "B-Type 수량": "3", "C-Type 수량": "3"},
    "보통인부": {"A-Type 수량": "1", "B-Type 수량": "1", "C-Type 수량": "1"},
    "굴착기": {"A-Type 수량": "1", "B-Type 수량": "1", "C-Type 수량": "1"},
    "로더(타이어)": {"A-Type 수량": "1", "B-Type 수량": "1"},
    "진동롤러(진동+타이어)": {"A-Type 수량": "1", "B-Type 수량": "1"},
    "진동롤러(핸드가이드식)": {"C-Type 수량": "1"},
    "플레이트콤팩터": {"C-Type 수량": "1"},
    "아스팔트스프레이어": {"A-Type 수량": "1", "B-Type 수량": "1", "C-Type 수량": "1"},
    "트럭": {"A-Type 수량": "2", "B-Type 수량": "2", "C-Type 수량": "2"},
}
type_values = {"A Type": "A-Type", "B Type": "B-Type", "C Type": "C-Type"}
draft["inputs"] = [
    next(item for item in draft["inputs"] if item["name"] == "repair_type"),
    {"name": "area_per_location", "type": "positive_rational", "allowed_values": "0보다 큰 수",
     "unit": "㎡", "required": True, "ask": "개소별 평균 시공면적은 몇 ㎡입니까?",
     "source": "PDF 878~879쪽 ⑤ 시공량 할증계수 표"},
    next(item for item in draft["inputs"] if item["name"] == "total_area"),
]
tables = {item["id"]: item for item in draft["tables"]}
tables["p934-t1"]["source"] = "PDF 878쪽 2-1-9 (일당) 표; 직종 행과 시공량 열을 원문 셀에서 재구성"
tables["p934-t4"]["source"] = "PDF 878쪽 2-1-9 ⑤ A-Type 시공량 할증계수 표"
tables["p935-t0"]["source"] = "PDF 879쪽 2-1-9 ⑤ B-Type 시공량 할증계수 표"
tables["p935-t1"]["source"] = "PDF 879쪽 2-1-9 ⑤ C-Type 시공량 할증계수 표"
draft["quantity_model"] = {
    "name": "adjusted_daily_crew",
    "params": {
        "base_output": {"table": "p934-t1", "row": "시공량",
                        "column_selector": {"input": "repair_type",
                            "contains": ["{value} 시공량(㎡)"], "value_map": type_values}},
        "coefficients": [{"table": "p934-t4", "table_selector": {
            "input": "repair_type", "values": {"A Type": "p934-t4", "B Type": "p935-t0", "C Type": "p935-t1"}},
            "row": "시공량 할증계수", "input": "area_per_location", "selector_mode": "threshold"}],
        "crew": {"table": "p934-t1", "trades": ["포장공", "보통인부"],
                 "column_selector": {"input": "repair_type", "contains": ["{value} 수량"],
                                     "value_map": type_values}},
        "equipment": [
            {"table": "p934-t1", "name": row, "row": row,
             "column": f"{type_values[type_name]} 수량", "unit": "대·일", "when": {"repair_type": type_name}}
            for type_name, rows in {
                "A Type": ["굴착기", "로더(타이어)", "진동롤러(진동+타이어)", "아스팔트스프레이어", "트럭"],
                "B Type": ["굴착기", "로더(타이어)", "진동롤러(진동+타이어)", "아스팔트스프레이어", "트럭"],
                "C Type": ["굴착기", "진동롤러(핸드가이드식)", "플레이트콤팩터", "아스팔트스프레이어", "트럭"],
            }.items() for row in rows
        ],
        "quantity_input": "total_area",
    },
    "steps": [
        "현장 여건에 해당하는 p934-t3의 A/B/C Type을 선택한다.",
        "개소별 평균면적으로 해당 Type의 p934-t4, p935-t0 또는 p935-t1 원문 구간을 선택한다.",
        "보정 일당시공량 = 기준 시공량 × 원문 시공량 할증계수로 계산한다.",
        "작업일수 = 총 시공면적 ÷ 보정 일당시공량으로 계산하고 원문 Type별 직종 및 장비 수량을 곱한다.",
    ],
    "source": "PDF 878~879쪽 2-1-9 기준 (일당) 표, ④~⑦ 주",
    "rounding": "총 투입량은 정확한 유리수로 보존; 단위당 품은 공통 1-2-8·1-2-1 기본 자릿수 적용",
}
draft["blocked"] = []
draft["open_questions"] = []
package["open_questions"] = []
package["questions"] = package["questions"][:2]
draft["calc_type_reason"] = "원문 p934-t1의 포장공·보통인부 행을 분리하고 A/B/C별 시공량과 장비 수량을 연결했다. 개소 평균면적 할증표의 정확한 구간 선택을 실행기에 연결했다. 제목 위에 있는 절삭 없는 덧씌우기 주석은 앞 절에 귀속됨을 페이지 위치로 확인해 제외했다."
package["calc_type"] = "daily_crew"
PATH.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("reconstructed", draft["id"])

"""공통 8-2-3 굴착기: 원문 p.172~173(PDF 228~229) 시간당 작업량 식을 기존 formula 계산기로 연결한다.

원문 이미지 대조: 파쇄암 E는 흐트러진 상태 보통 0.45·불량 0.35 두 칸뿐이다. 추출본에 있던
'자연상태 불량 0.45'는 칸 위치 오류이므로 제거한다.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data/drafts/specs/공통/8-2-3.json"
package = json.loads(PATH.read_text(encoding="utf-8"))
draft = package["draft"]
tables = {t["id"]: t for t in draft["tables"]}
tables["p228-t1"]["values"]["파쇄암"].pop("자연상태 불량", None)
assert tables["p228-t1"]["values"]["파쇄암"] == {"흐트러진 상태 보통": "0.45", "흐트러진 상태 불량": "0.35"}

k_rows = list(tables["p228-t0"]["values"])
fields = {f["name"]: f for f in draft["inputs"]}
assert k_rows == fields["bucket_condition"]["allowed_values"]
cases_e = [
    {"when": {"is_residential_area": True, "is_underwater": False, "soil_state": "자연상태"},
     "table": "p229-t0", "row_input": "soil_type", "column_join": ["soil_state", "site_condition"]},
    {"when": {"is_residential_area": True, "is_underwater": True, "soil_state": "자연상태"},
     "table": "p229-t0", "row_input": "soil_type", "column": "자연상태 불량"},
    {"when": {"is_residential_area": False, "is_underwater": False},
     "table": "p228-t1", "row_input": "soil_type", "column_join": ["soil_state", "site_condition"]},
    {"when": {"is_residential_area": False, "is_underwater": True, "soil_state": "자연상태"},
     "table": "p228-t1", "row_input": "soil_type", "column": "자연상태 불량"},
    {"when": {"is_residential_area": False, "is_underwater": True, "soil_state": "흐트러진 상태"},
     "table": "p228-t1", "row_input": "soil_type", "column": "흐트러진 상태 불량"},
]
derived = [
    {"name": "K", "kind": "table_cell", "unit": "", "source": "PDF 172쪽 1. 버킷계수(K)",
     "cases": [{"when": {"bucket_condition": row}, "table": "p228-t0", "row": row, "column": "K"} for row in k_rows]},
    {"name": "E_table", "kind": "table_cell", "unit": "", "source": "PDF 172~173쪽 2. 작업효율(E) [주] ③⑦", "cases": cases_e},
    {"name": "E_deduction", "kind": "sum_terms", "source": "PDF 172쪽 2. 작업효율(E) [주] ④ 터파기 0.05를 뺀다",
     "terms": [{"when": {"is_trenching": True}, "value": "1/20"}]},
    {"name": "E", "kind": "expression", "unit": "", "expression": {"sub": [{"input": "E_table"}, {"input": "E_deduction"}]}},
    {"name": "cm", "kind": "table_cell", "unit": "초", "source": "PDF 173쪽 3. 1회 싸이클시간(cm)",
     "cases": [{"when": {"swing_angle": a}, "table": "p229-t1", "row_input": "excavator_capacity",
                "column": f"싸이클시간(Sec) {a}"} for a in ("45", "90", "135", "180")]},
]
outputs = [{"kind": "formula", "name": "시간당 작업량 Q", "resource_kind": "reference", "unit": "㎥/hr",
            "expression": {"div": [{"mul": [{"number": "3600"}, {"input": "bucket_capacity"}, {"input": "K"},
                                            {"input": "volume_conversion_factor"}, {"input": "E"}]}, {"input": "cm"}]},
            "formula": "Q = 3,600 × q × K × f × E / cm", "source": "PDF 172쪽 8-2-3 산정식"}]
qm = draft["quantity_model"]
draft["quantity_model"] = {"name": "formula", "params": {"derived": derived, "outputs": outputs},
                           "steps": qm["steps"], "source": qm["source"], "rounding": qm["rounding"]}
draft["blocked"] = draft["blocked"] + [
    {"condition": "주택가지역 작업효율(⑦)과 터파기 감산(④)이 함께 적용되는 경우",
     "blocked_if_all": [{"input": "is_residential_area", "op": "==", "value": True},
                        {"input": "is_trenching", "op": "==", "value": True}],
     "reason": "⑦의 작업효율 표에 터파기 0.05 감산을 함께 적용하는지 원문이 정하지 않는다.",
     "source": "PDF 172~173쪽 2. 작업효율(E) [주] ④⑦"}]
package["calc_type"] = "formula"
package["calc_type_reason"] = "원문 K·E·cm 표와 Q 산정식으로 시간당 작업량(참조값)을 선언형 formula로 계산. 파쇄암 E 칸 위치는 원문 이미지로 교정."
PATH.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("ok")

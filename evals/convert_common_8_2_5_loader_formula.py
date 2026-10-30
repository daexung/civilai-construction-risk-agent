"""공통 8-2-5 로더: 원문 p.175(PDF 231) 시간당 작업량 식을 기존 formula 계산기로 연결한다.

E 표는 추출에서 열 단위로 깨져 명세에 없었으므로 원문 이미지(파쇄암은 흐트러진 상태 3칸만 있음)로 복구한다.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data/drafts/specs/공통/8-2-5.json"
package = json.loads(PATH.read_text(encoding="utf-8"))
draft = package["draft"]

SOIL = ["모래, 사질토", "자갈 섞인 흙, 점성토", "파쇄암"]
E_ROWS = {  # 원문 3. E의 값 (빈 칸은 원문에 값이 없음)
    SOIL[0]: {"자연상태 양호": "0.70", "자연상태 보통": "0.55", "자연상태 불량": "0.40",
              "흐트러진 상태 양호": "0.75", "흐트러진 상태 보통": "0.60", "흐트러진 상태 불량": "0.45"},
    SOIL[1]: {"자연상태 양호": "0.60", "자연상태 보통": "0.45", "자연상태 불량": "0.30",
              "흐트러진 상태 양호": "0.60", "흐트러진 상태 보통": "0.50", "흐트러진 상태 불량": "0.35"},
    SOIL[2]: {"흐트러진 상태 양호": "0.55", "흐트러진 상태 보통": "0.35", "흐트러진 상태 불량": "0.25"},
}
draft["tables"] = [t for t in draft["tables"] if t["id"] != "p231-t2"] + [
    {"id": "p231-t2", "unit": "무차원", "source": "PDF 175쪽 3. E의 값", "values": E_ROWS}]

CM = {"chunk_id": "p230-x9", "quote": "cm = m･ℓ+ t1 + t2"}
t1_cases = [{"when": {"loader_type": lt, "t1_method": m}, "table": "p230-t0", "row_input": "t1_condition",
             "column": f"{lt} {col}"}
            for lt in ("무한궤도식", "타이어식")
            for m, col in (("산적상태에서 담을 때", "산적상태에서\n담을 때"),
                           ("지면부터 굴착 집토하여 담을 때", "지면부터 굴착\n집토하여 담을 때"))]
k_values = {t["id"]: list(t["values"]) for t in draft["tables"] if t["id"] in ("p231-t0", "p231-t1")}
k_cases = [{"when": {"k_condition": row}, "table": tid, "row": row, "column": "계수"}
           for tid, rows in k_values.items() for row in rows]
assert len(k_cases) == 5
e_cases = [{"when": {"loader_type": "타이어식", "e_state": "흐트러진 상태", "e_soil_type": soil},
            "table": "p231-t2", "row": soil, "column": "흐트러진 상태 양호",
            "cite": {"chunk_id": "p231-x13", "quote": "⑧ 타이어식 로더의 적용은 흐트러진 상태에서 파쇄암 이외의 토질 적재시 현장조건은 양호한 것으로 한다."}}
           for soil in SOIL[:2]]
e_cases = [{k: v for k, v in c.items() if k != "cite"} for c in e_cases]
e_cases += [{"when": {"loader_type": "무한궤도식"}, "table": "p231-t2", "row_input": "e_soil_type",
             "column_join": ["e_state", "e_condition"]},
            {"when": {"loader_type": "타이어식", "e_state": "자연상태"}, "table": "p231-t2",
             "row_input": "e_soil_type", "column_join": ["e_state", "e_condition"]},
            {"when": {"loader_type": "타이어식", "e_state": "흐트러진 상태", "e_soil_type": SOIL[2]},
             "table": "p231-t2", "row_input": "e_soil_type", "column_join": ["e_state", "e_condition"]}]

derived = [
    {"name": "m", "kind": "table_cell", "unit": "초/m", "cases": [
        {"when": {"loader_type": "무한궤도식"}, "value": "2.0", "cite": {"chunk_id": "p230-x9", "quote": "m : 계수(초/m) 무한궤도식 : 2.0"}},
        {"when": {"loader_type": "타이어식"}, "value": "1.8", "cite": {"chunk_id": "p230-x9", "quote": "타 이 어 식 : 1.8"}}]},
    {"name": "t1", "kind": "table_cell", "unit": "초", "source": "PDF 174쪽 1. t1의 값", "cases": t1_cases},
    {"name": "t2", "kind": "table_cell", "unit": "초", "cases": [
        {"when": {}, "value": "14", "cite": {"chunk_id": "p230-x9", "quote": "t2 : 기어변화 등 기본 시간과 다음 운반기계가 도착할 때까지의 시간(14초)"}}]},
    {"name": "cm", "kind": "expression", "unit": "초", "source": "PDF 174쪽 cm = m·ℓ + t1 + t2", "cite": CM,
     "expression": {"add": [{"mul": [{"input": "m"}, {"input": "l"}]}, {"input": "t1"}, {"input": "t2"}]}},
    {"name": "K", "kind": "table_cell", "unit": "", "source": "PDF 175쪽 2. K의 값", "cases": k_cases},
    {"name": "E_table", "kind": "table_cell", "unit": "", "source": "PDF 175쪽 3. E의 값 [주] ⑧", "cases": e_cases},
    {"name": "E_deduction", "kind": "sum_terms", "source": "PDF 175쪽 3. E의 값 [주] ⑤ 터파기 0.05를 뺀다",
     "terms": [{"when": {"is_trench": True}, "value": "1/20"}],
     "cite": {"chunk_id": "p231-x13", "quote": "⑤ 터파기에 대하여는 0.05를 뺀 값으로 한다."}},
    {"name": "E", "kind": "expression", "unit": "", "expression": {"sub": [{"input": "E_table"}, {"input": "E_deduction"}]}},
]
outputs = [
    {"kind": "formula", "name": "1회 싸이클 시간 cm", "resource_kind": "reference", "unit": "초",
     "expression": {"input": "cm"}, "formula": "cm = m×ℓ + t1 + t2", "source": "PDF 174쪽 8-2-5 cm", "cite": CM},
    {"kind": "formula", "name": "시간당 작업량 Q", "resource_kind": "reference", "unit": "㎥/hr",
     "expression": {"div": [{"mul": [{"number": "3600"}, {"input": "q"}, {"input": "K"}, {"input": "f"}, {"input": "E"}]}, {"input": "cm"}]},
     "formula": "Q = 3,600 × q × K × f × E / cm", "source": "PDF 174쪽 8-2-5 산정식"},
]
qm = draft["quantity_model"]
draft["quantity_model"] = {"name": "formula", "params": {"derived": derived, "outputs": outputs},
                           "steps": qm["steps"], "source": qm["source"], "rounding": qm["rounding"]}
draft["blocked"] = [{
    "condition": "타이어식 로더로 발파암 및 암괴 등을 적재하는 경우",
    "blocked_if_all": [{"input": "loader_type", "op": "==", "value": "타이어식"},
                       {"input": "k_condition", "op": "==", "value": k_values["p231-t1"][2]}],
    "reason": "발파암 및 암괴 등을 적재할 경우는 무한궤도식 로더로 계상해야 함",
    "source": "PDF 175쪽 2. K의 값 [주] ②",
    "cite": {"chunk_id": "p231-x6", "quote": "단, 발파암 및 암괴 등을 적재할 경우는 무한궤도식 로더로 계상한다."}}]
package["calc_type"] = "formula"
package["calc_type_reason"] = "원문 t1·K·E 표와 cm·Q 식으로 시간당 작업량(참조값)을 선언형 formula로 계산. E 표는 원문 이미지로 복구."
PATH.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("ok")

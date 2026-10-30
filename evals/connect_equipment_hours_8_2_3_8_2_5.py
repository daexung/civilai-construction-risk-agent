"""로더(8-2-5)·굴착기(8-2-3): 장비 규격→q, 토량 기준→f, 작업량 Q와 물량으로 장비시간을 내고 기계경비에 연결한다.

q는 버킷용량이므로 건설기계 경비산출표의 장비 규격(㎥)을 그대로 쓴다. f는 1-2-3 체적환산계수 표(p65-t1)의
'흐트러진 상태 기준 자연상태 환산 = 1/L'과 '흐트러진 상태 = 1'만 쓴다(L은 현장 시험값, 범위 표값을 고르지 않는다).
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
rates = json.loads((ROOT / "data/rates/equipment_rates.json").read_text(encoding="utf-8"))["machines"]
VOL_CITE = {"table_id": "p65-t1", "row": "흐트러진상태의체적", "column": "자연상태의체적", "value": "1/L"}


def machines(prefix: str) -> dict[str, str]:
    return {m["spec"]: code for code, m in rates.items() if code.startswith(prefix)}


def common_inputs(draft: dict, drop: set[str], machine_codes, extra_first: list[dict]) -> None:
    draft["inputs"] = ([f for f in draft["inputs"] if f["name"] not in drop and f["name"] not in
                        {"machine_spec", "volume_basis", "L", "quantity", "fuel_price"}] + extra_first)


def tail_inputs(machine_field: dict) -> list[dict]:
    return [machine_field,
            {"name": "volume_basis", "type": "enum", "allowed_values": ["자연상태", "흐트러진 상태"], "unit": None,
             "required": True, "ask": "작업 물량은 자연상태 기준입니까, 흐트러진 상태 기준입니까?",
             "source": "PDF 1-2-3 체적환산계수 표"},
            {"name": "L", "type": "positive_rational", "allowed_values": "0보다 큰 수", "unit": None, "required": False,
             "required_when": {"input": "volume_basis", "equals": "자연상태"},
             "ask": "토량변화율 L(흐트러진 상태 체적/자연상태 체적)은 얼마입니까? (현장 시험값)",
             "source": "PDF 1-2-3 체적환산계수 표"},
            {"name": "quantity", "type": "positive_rational", "allowed_values": "0보다 큰 수", "unit": "㎥",
             "required": True, "ask": "작업할 토량은 몇 ㎥입니까?", "source": "현장 물량"},
            {"name": "fuel_price", "type": "positive_rational", "allowed_values": "0보다 큰 수", "unit": "원/ℓ",
             "required": True, "ask": "경유(주연료) 단가는 ℓ당 몇 원입니까? (해당 지역 가격, 품셈 8-1-7)",
             "source": "품셈 8-1-7 유류가격은 해당지역의 가격"}]


def base_derived(q_cases: list[dict]) -> list[dict]:
    return [
        {"name": "q", "kind": "table_cell", "unit": "㎥", "source": "장비 규격 = 버킷용량 q", "cases": q_cases},
        {"name": "L_eff", "kind": "table_cell", "unit": "", "source": "1-2-3 체적환산계수", "cases": [
            {"when": {"volume_basis": "자연상태"}, "input_value": "L", "cite": VOL_CITE},
            {"when": {"volume_basis": "흐트러진 상태"}, "value": "1", "cite": VOL_CITE}]},
        {"name": "f", "kind": "expression", "unit": "", "source": "f = 1/L (자연상태 환산), 흐트러진 상태 1",
         "expression": {"div": [{"number": "1"}, {"input": "L_eff"}]}}]


def finish(draft: dict, derived_head: list[dict], derived_tail: list[dict], hours_name: str, equipment: dict) -> None:
    params = draft["quantity_model"]["params"]
    drop = {"q", "f", "L_eff", "Q"}
    params["derived"] = derived_head + [d for d in params["derived"] if d["name"] not in drop] + derived_tail
    q_expr = {"div": [{"mul": [{"number": "3600"}, {"input": "q"}, {"input": "K"}, {"input": "f"}, {"input": "E"}]}, {"input": "cm"}]}
    params["derived"].append({"name": "Q", "kind": "expression", "unit": "㎥/hr", "expression": q_expr,
                              "source": "Q = 3,600 × q × K × f × E / cm"})
    params["outputs"] = [o for o in params["outputs"] if o.get("name") not in ("시간당 작업량 Q", hours_name)] + [
        {"kind": "formula", "name": "시간당 작업량 Q", "resource_kind": "reference", "unit": "㎥/hr",
         "expression": {"input": "Q"}, "formula": "Q = 3,600 × q × K × f × E / cm"},
        {"kind": "formula", "name": hours_name, "resource_kind": "equipment", "unit": "hr",
         "expression": {"div": [{"number": "1"}, {"input": "Q"}]},
         "formula": "장비 가동시간(기준 물량 1㎥당) = 1 ÷ 시간당 작업량 Q (Q와 물량은 같은 토량 기준)",
         "source": "PDF 8-2 시간당 작업량 Q의 정의(㎥/hr)"}]
    params["equipment"] = {**equipment, "fuel_price_input": "fuel_price"}
    params["quantity_input"] = "quantity"
    draft["quantity_model"]["rounding"] = "총 투입량은 정확한 유리수로 보존"


# ---- 로더 8-2-5 ----
path = ROOT / "data/drafts/specs/공통/8-2-5.json"
package = json.loads(path.read_text(encoding="utf-8"))
draft = package["draft"]
codes = {"무한궤도식": machines("0301"), "타이어식": machines("0302")}
draft["inputs"] = [f for f in draft["inputs"] if f["name"] not in {"q", "f", "machine_spec", "volume_basis", "L", "quantity", "fuel_price"}]
machine_field = {"name": "machine_spec", "type": "enum", "unit": "㎥", "required": True,
                 "allowed_values": sorted({s for c in codes.values() for s in c}, key=lambda s: float(s[:-1])),
                 "ask": "로더의 규격(버킷용량)은 무엇입니까?", "machine_codes": codes,
                 "source": "2026년도 건설기계 경비산출표 로더"}
draft["inputs"] += tail_inputs(machine_field)
q_cases = [{"when": {"loader_type": t, "machine_spec": s}, "value": s[:-1],
            "cite": {"chunk_id": "p230-x9", "quote": "q : 버킷용량(㎥)"}} for t, c in codes.items() for s in c]
finish(draft, base_derived(q_cases), [], "로더",
       {"line_name": "로더", "label": "로더", "machine_code_input": "machine_spec",
        "machine_type_input": "loader_type", "operator_rate_code": "1048"})
package["calc_type_reason"] += " 장비 규격→q, 장비 가동시간·기계경비 연결."
path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

# ---- 굴착기 8-2-3 ----
path = ROOT / "data/drafts/specs/공통/8-2-3.json"
package = json.loads(path.read_text(encoding="utf-8"))
draft = package["draft"]
codes = machines("0201")
cls = lambda s: next(c for c, lo, hi in (("0.12∼0.4", 0.12, 0.4), ("0.6∼0.8", 0.6, 0.8), ("1.0∼1.2", 1.0, 1.2), ("2.0", 2.0, 2.0))
                     if lo <= float(s[:-1]) <= hi)
draft["inputs"] = [f for f in draft["inputs"] if f["name"] not in
                   {"bucket_capacity", "volume_conversion_factor", "excavator_capacity", "machine_spec", "volume_basis", "L", "quantity", "fuel_price"}]
machine_field = {"name": "machine_spec", "type": "enum", "unit": "㎥", "required": True, "allowed_values": list(codes),
                 "ask": "굴착기의 규격(버킷용량)은 무엇입니까?", "machine_codes": codes,
                 "source": "2026년도 건설기계 경비산출표 굴착기(무한궤도)"}
draft["inputs"] += tail_inputs(machine_field)
q_cases = [{"when": {"machine_spec": s}, "value": s[:-1], "cite": {"chunk_id": "p228-x0", "quote": "q : 버킷용량(㎥)"}} for s in codes]
cm = next(d for d in draft["quantity_model"]["params"]["derived"] if d["name"] == "cm")
cm["cases"] = [{"when": {"machine_spec": s, "swing_angle": a}, "table": "p229-t1", "row": cls(s),
                "column": f"싸이클시간(Sec) {a}"} for s in codes for a in ("45", "90", "135", "180")]
finish(draft, base_derived(q_cases), [], "굴착기",
       {"line_name": "굴착기", "label": "굴착기", "machine_code_input": "machine_spec", "operator_rate_code": "1048"})
path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("ok")

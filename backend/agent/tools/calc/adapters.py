"""formula·lookup 계산 결과를 상담·단가·집계가 읽는 공통 결과 모양으로 맞춘다.

두 계산기는 입력 물량을 이미 반영한 '총량' 줄을 낸다(단위당 품이 아니다). 상담 계층은 줄마다
(단위당 값 × provenance.quantity)로 표시·집계하므로, 총량 줄은 물량 1(1식)을 기준으로 둔다.
값을 물량으로 다시 나누지 않아 정확한 유리수가 보존된다. lookup 줄은 금액이 아니라 조회 값이라
reference_only로 표시하고 단가·합산 대상에서 뺀다.
"""
from __future__ import annotations

from backend.agent.tools.calc.formula import formula_quantity
from backend.agent.tools.calc.lookup import lookup

TOTALS_BASIS = {"per": "1식(입력 물량 기준 총량)", "daily_output": "", "places": 0,
                "adjustable_note": "입력한 물량·조건을 이미 반영한 총량 값"}


def _as_totals(result: dict, *, reference_only: bool) -> dict:
    if result.get("status") != "computed":
        return result
    provenance = dict(result.get("provenance") or {})
    provenance["quantity"] = "1"
    out = {**result, "provenance": provenance, "unit_basis": dict(TOTALS_BASIS), "result_kind": "totals",
           "adjustment_memos": result.get("adjustment_memos", [])}
    if reference_only:
        out["reference_only"] = True
    return out


REFERENCE_KINDS = ("lookup", "reference")


def formula_adapter(spec: dict, inputs: dict, *, labor_only: bool = False, **_: object) -> dict:
    result = formula_quantity(spec, inputs)
    # 시간당 작업량처럼 금액이 아닌 참조 값만 내는 공식은 조회와 같이 금액·합산에서 뺀다
    lines = result.get("unit_lines") or []
    return _as_totals(result, reference_only=bool(lines) and all(l["kind"] in REFERENCE_KINDS for l in lines))


def lookup_adapter(spec: dict, inputs: dict, *, labor_only: bool = False, **_: object) -> dict:
    return _as_totals(lookup(spec, inputs), reference_only=True)

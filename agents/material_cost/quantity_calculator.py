"""
Quantity Change Calculator Tool
- 추가 물량 발생 시 자재비 계산
- 계약단가 기준 / 현재단가 기준 / 차액 모두 계산
- 시황성 자재 여부에 따른 주의 메시지 포함
"""

import json
from typing import Optional
from langchain_core.tools import tool


# ── 코어 함수들 (순수 dict 반환, ReAct agent에 노출되지 않음) ─────────────────

def _calculate_quantity_change_cost_core(
    material_name: str,
    quantity: float,
    unit: str,
    current_unit_price: float,
    contract_unit_price: Optional[float] = None,
    is_market_sensitive: bool = False,
    contract_type: str = "고정단가",
    vat_included: bool = False,
) -> dict:
    """추가 물량 자재비 계산 로직. 결과를 dict로 반환.

    # TODO(Tier 2): 코어를 직접 호출하는 deterministic 노드를 만들 때
    # 이 함수가 raise하는 Exception을 노드 쪽에서도 별도로 처리해야 함.
    # 현재는 @tool 셸의 except 블록에서만 잡고 있음.
    """
    # --- 현재단가 기준 계산 ---
    cost_by_current = quantity * current_unit_price
    vat_by_current = cost_by_current * 0.1 if not vat_included else 0
    total_by_current = cost_by_current + vat_by_current

    result = {
        "status": "success",
        "자재명": material_name,
        "추가물량": quantity,
        "단위": unit,
        "현재단가_원": current_unit_price,
        "현재단가_기준": {
            "추가자재비_원": round(cost_by_current),
            "부가세_원": round(vat_by_current),
            "합계_원": round(total_by_current),
            "합계_만원": round(total_by_current / 10000, 1),
        },
    }

    # --- 계약단가 기준 계산 (계약단가가 있을 때) ---
    if contract_unit_price is not None and contract_unit_price > 0:
        cost_by_contract = quantity * contract_unit_price
        vat_by_contract = cost_by_contract * 0.1 if not vat_included else 0
        total_by_contract = cost_by_contract + vat_by_contract

        price_diff = current_unit_price - contract_unit_price
        cost_diff = total_by_current - total_by_contract
        diff_ratio = (price_diff / contract_unit_price) * 100

        result["계약단가_원"] = contract_unit_price
        result["계약단가_기준"] = {
            "추가자재비_원": round(cost_by_contract),
            "부가세_원": round(vat_by_contract),
            "합계_원": round(total_by_contract),
            "합계_만원": round(total_by_contract / 10000, 1),
        }
        result["단가차액분석"] = {
            "단가차이_원": round(price_diff),
            "비용차이_원": round(cost_diff),
            "비용차이_만원": round(cost_diff / 10000, 1),
            "단가변동률_pct": round(diff_ratio, 2),
            "현재단가가_더_높음": price_diff > 0,
        }

        # LLM 필드 선택 혼동 방지: 정산 기준 금액과 참고 차액을 명확히 분리한다
        if contract_type == "고정단가":
            result["material_cost_krw"] = round(cost_by_contract)
            result["price_diff_reference_krw"] = round(cost_by_current - cost_by_contract)
            result["settlement_basis"] = "fixed_contract_price"
            result["basis"] = (
                f"고정단가 계약: {contract_unit_price:,.0f}원/{unit} × {quantity}{unit}"
                f" = {round(cost_by_contract):,}원"
                f" | [중요] cost_items[].amount 및 total_cost에는 반드시 이 값"
                f"({round(cost_by_contract):,})을 사용하고"
                f" price_diff_reference_krw({round(cost_by_current - cost_by_contract):,})는"
                f" assumptions에만 기록한다"
            )
        else:  # 시가연동
            result["material_cost_krw"] = round(cost_by_current)
            result["price_diff_reference_krw"] = round(cost_by_current - cost_by_contract)
            result["settlement_basis"] = "current_market_price"
            result["basis"] = (
                f"시가연동 계약: {current_unit_price:,.0f}원/{unit} × {quantity}{unit}"
                f" = {round(cost_by_current):,}원"
                f" | [중요] cost_items[].amount 및 total_cost에는 반드시 이 값"
                f"({round(cost_by_current):,})을 사용한다"
            )
    else:
        # 계약단가 없음: 현재단가 기준으로만 계산
        result["material_cost_krw"] = round(cost_by_current)
        result["price_diff_reference_krw"] = 0
        result["settlement_basis"] = "current_market_price"
        result["basis"] = (
            f"현재단가 기준: {current_unit_price:,.0f}원/{unit} × {quantity}{unit}"
            f" = {round(cost_by_current):,}원"
            f" | [중요] cost_items[].amount 및 total_cost에는 반드시 이 값"
            f"({round(cost_by_current):,})을 사용한다"
        )

    # --- 시황성 / 계약유형 주의사항 ---
    notes = []
    if is_market_sensitive:
        notes.append(
            "⚠️ 이 자재는 시황성 자재입니다. "
            "공시 이후 실제 구매 시점에 단가가 달라질 수 있습니다."
        )
    if contract_type == "시가연동":
        notes.append(
            "📋 계약 유형이 '시가연동'입니다. "
            "현재단가 기준으로 청구 가능한지 계약 조건을 확인하세요."
        )
    if contract_unit_price is None:
        notes.append(
            "ℹ️ 계약단가가 입력되지 않았습니다. "
            "Project Context DB에서 계약단가를 확인 후 재계산하세요."
        )
    if not vat_included:
        notes.append("ℹ️ 부가세(10%)는 별도로 계산되었습니다.")

    result["주의사항"] = notes
    result["계약유형"] = contract_type

    return result


def _calculate_total_material_cost_core(items: list[dict]) -> dict:
    """여러 자재 추가비용 합산 로직. 결과를 dict로 반환. items는 비어있지 않다고 가정.

    # TODO(Tier 2): 코어를 직접 호출하는 deterministic 노드를 만들 때
    # 이 함수가 raise하는 Exception을 노드 쪽에서도 별도로 처리해야 함.
    # 현재는 @tool 셸의 except 블록에서만 잡고 있음.
    """
    total = 0
    breakdown = []
    for item in items:
        cost = float(item.get("추가비용_원", 0))
        total += cost
        breakdown.append(
            {
                "자재명": item.get("자재명", "알 수 없음"),
                "추가비용_원": round(cost),
                "추가비용_만원": round(cost / 10000, 1),
                "단가기준": item.get("단가기준", "미확인"),
            }
        )

    return {
        "status": "success",
        "항목별_비용": breakdown,
        "총_추가자재비_원": round(total),
        "총_추가자재비_만원": round(total / 10000, 1),
        "총_추가자재비_억원": round(total / 100_000_000, 3),
    }


# ── @tool 셸 함수들 (입출력 시그니처 동결 — ReAct agent가 호출) ──────────────

@tool
def calculate_quantity_change_cost(
    material_name: str,
    quantity: float,
    unit: str,
    current_unit_price: float,
    contract_unit_price: Optional[float] = None,
    is_market_sensitive: bool = False,
    contract_type: str = "고정단가",
    vat_included: bool = False,
) -> str:
    """
    추가 물량 발생에 따른 자재비를 계산합니다.

    Args:
        material_name: 자재명 (예: "H파일")
        quantity: 추가 물량 수치 (예: 500)
        unit: 단위 (예: "ton", "m²", "EA")
        current_unit_price: 현재 단가 (원/단위, 조달청 기준)
        contract_unit_price: 계약 단가 (원/단위). None이면 현재단가만으로 계산
        is_market_sensitive: 시황성 자재 여부 (단가 변동 가능성)
        contract_type: 계약 유형 ("고정단가" 또는 "시가연동")
        vat_included: 부가세 포함 여부 (False면 별도 계산)

    Returns:
        계약단가/현재단가 기준 추가비용, 차액, 시황성 주의사항 포함 JSON
    """
    try:
        return json.dumps(
            _calculate_quantity_change_cost_core(
                material_name, quantity, unit, current_unit_price,
                contract_unit_price, is_market_sensitive, contract_type, vat_included,
            ),
            ensure_ascii=False,
            indent=2,
        )
    except Exception as e:
        return json.dumps(
            {"status": "error", "message": f"계산 중 오류 발생: {str(e)}"},
            ensure_ascii=False,
        )


@tool
def calculate_total_material_cost(items: list[dict]) -> str:
    """
    여러 자재의 추가비용을 합산합니다.

    Args:
        items: 자재별 비용 딕셔너리 리스트.
               각 항목: {"자재명": str, "추가비용_원": float, "단가기준": str}

    Returns:
        항목별 + 총합 비용 JSON
    """
    # 빈배열 pre-check: 원본 동작과 동일하게 indent 없이 반환
    if not items:
        return json.dumps(
            {"status": "error", "message": "items가 비어있습니다."},
            ensure_ascii=False,
        )
    try:
        return json.dumps(
            _calculate_total_material_cost_core(items), ensure_ascii=False, indent=2
        )
    except Exception as e:
        return json.dumps(
            {"status": "error", "message": f"합산 오류: {str(e)}"}, ensure_ascii=False
        )

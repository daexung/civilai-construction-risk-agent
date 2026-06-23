"""Material cost calculation service.

도메인 계산 로직의 단일 진입점.
agents/router/nodes/material_node.py 는 이 모듈을 호출하는 얇은 adapter 역할만 한다.
"""
from __future__ import annotations

import importlib.util
import json
import logging
import os
import re
import sys
from typing import Any

_log = logging.getLogger(__name__)

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))

if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ── 도구 모듈 로드 ─────────────────────────────────────────────────────────────
# importlib.util로 고유한 이름을 부여해 sys.modules 충돌 방지
def _load_tool_module(unique_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(
        unique_name, os.path.join(_HERE, filename)
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_price_module = _load_tool_module("material_price_core_svc", "material_price_tool.py")
_quantity_module = _load_tool_module("material_quantity_core_svc", "quantity_calculator.py")

_search_material_price_core = _price_module._search_material_price_core
_calculate_quantity_change_cost_core = _quantity_module._calculate_quantity_change_cost_core
_calculate_total_material_cost_core = _quantity_module._calculate_total_material_cost_core

try:
    from rag.company_docs.search import search_contract_price as _search_contract_price_tool
except Exception as _exc:
    _search_contract_price_tool = None
    _log.warning("company_docs contract price RAG tool unavailable: %s", _exc)


# ── 상수 ───────────────────────────────────────────────────────────────────────
_EXCLUDED_ITEMS = ["인건비", "장비비", "이윤", "부가세"]
_STATUS_VALUES = {"CALCULATED", "MISSING_INFO", "PARTIAL", "ERROR"}

_MATERIAL_NAME_KEYS = (
    "material_name", "material", "item_name", "name", "item", "자재명", "품목",
)
_QUANTITY_KEYS = ("quantity", "qty", "amount_quantity", "수량", "물량", "추가물량")
_UNIT_KEYS = ("unit", "단위")
_CURRENT_PRICE_KEYS = (
    "current_unit_price", "unit_price", "current_price", "current_rate",
    "현재단가", "현재단가_원", "조달청단가",
)
_CONTRACT_PRICE_KEYS = (
    "contract_unit_price", "contract_price", "contract_rate", "계약단가", "계약단가_원",
)
_MARKET_SENSITIVE_KEYS = ("is_market_sensitive", "market_sensitive", "시황성자재")
_VAT_INCLUDED_KEYS = ("vat_included", "부가세포함", "부가세여부")


# ── 유틸리티 ───────────────────────────────────────────────────────────────────

def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _append_unique(items: list, value: Any) -> None:
    if value is None or value == "":
        return
    if value not in items:
        items.append(value)


def _to_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "").replace("원", "")
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "yes", "y", "1", "포함", "부가세포함", "시황성", "시황성자재"}:
            return True
    return False


def _pick_number(source: dict, keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = _to_number(source.get(key))
        if value is not None:
            return value
    return None


def _pick_text(source: dict, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _pick_bool(source: dict, keys: tuple[str, ...]) -> bool:
    for key in keys:
        if key in source:
            return _to_bool(source.get(key))
    return False


def _normalize_contract_type(value: Any) -> str:
    text = str(value or "").strip()
    if text in {"시가연동", "변동단가", "시장가", "현재단가", "market", "variable"}:
        return "시가연동"
    return "고정단가"


def _material_lookup_candidates(material_name: str) -> list[str]:
    candidates: list[str] = []

    def add(value: str | None) -> None:
        if not value:
            return
        cleaned = value.strip()
        if cleaned and cleaned not in candidates:
            candidates.append(cleaned)

    add(material_name)
    compact = re.sub(r"\s+", "", material_name)
    add(compact)

    lowered = compact.lower()
    aliases = (
        ("h파일", "H파일"),
        ("phc파일", "PHC파일"),
        ("철근", "철근"),
        ("레미콘", "레미콘"),
        ("시멘트", "시멘트"),
        ("형강", "형강"),
        ("강관", "강관"),
    )
    for marker, alias in aliases:
        if marker in lowered or marker in compact:
            add(alias)

    return candidates


# ── 결과 구조 ──────────────────────────────────────────────────────────────────

def _base_result(status: str, summary: str) -> dict:
    return {
        "agent_name": "material",
        "domain": "자재비",
        "is_relevant": True,
        "status": status if status in _STATUS_VALUES else "ERROR",
        "summary": summary,
        "cost_items": [],
        "total_cost": 0,
        "missing_fields": [],
        "warnings": [],
        "assumptions": [],
        "excluded_items": list(_EXCLUDED_ITEMS),
        "evidence": [],
        "main_cause": "material",
    }


# ── 입력 spec 수집 ─────────────────────────────────────────────────────────────

def _quantity_value(item: Any) -> float | None:
    if isinstance(item, dict):
        return _pick_number(item, _QUANTITY_KEYS)
    return _to_number(item)


def _quantity_by_material(
    quantities: list, material_name: str | None
) -> tuple[float | None, str | None]:
    if not quantities:
        return None, None

    if material_name:
        for item in quantities:
            if not isinstance(item, dict):
                continue
            item_name = _pick_text(item, _MATERIAL_NAME_KEYS)
            if item_name and item_name == material_name:
                return _quantity_value(item), _pick_text(item, _UNIT_KEYS)

    if len(quantities) == 1:
        item = quantities[0]
        unit = _pick_text(item, _UNIT_KEYS) if isinstance(item, dict) else None
        return _quantity_value(item), unit

    return None, None


def _single_material_name_from(items: list) -> str | None:
    names = []
    for item in items:
        if isinstance(item, dict):
            name = _pick_text(item, _MATERIAL_NAME_KEYS)
            if name and name not in names:
                names.append(name)
    return names[0] if len(names) == 1 else None


def _specs_from_rates(inputs: dict) -> list[dict]:
    rates = _as_list(inputs.get("rates"))
    quantities = _as_list(inputs.get("quantities"))
    default_contract_type = inputs.get("contract_type")
    specs: list[dict] = []

    for rate in rates:
        if not isinstance(rate, dict):
            continue

        material_name = _pick_text(rate, _MATERIAL_NAME_KEYS)
        quantity = _pick_number(rate, _QUANTITY_KEYS)
        unit = _pick_text(rate, _UNIT_KEYS)
        if quantity is None:
            quantity, quantity_unit = _quantity_by_material(quantities, material_name)
            unit = quantity_unit or unit

        if material_name or quantity is not None or _pick_number(rate, _CURRENT_PRICE_KEYS) is not None:
            specs.append({
                "material_name": material_name,
                "quantity": quantity,
                "unit": unit,
                "current_unit_price": _pick_number(rate, _CURRENT_PRICE_KEYS),
                "contract_unit_price": _pick_number(rate, _CONTRACT_PRICE_KEYS),
                "contract_type": (
                    rate.get("contract_type")
                    or rate.get("rate_type")
                    or rate.get("계약유형")
                    or default_contract_type
                ),
                "is_market_sensitive": _pick_bool(rate, _MARKET_SENSITIVE_KEYS),
                "vat_included": _pick_bool(rate, _VAT_INCLUDED_KEYS),
                "source": "rates",
            })

    return specs


def _specs_from_quantities(inputs: dict) -> list[dict]:
    quantities = _as_list(inputs.get("quantities"))
    rates = _as_list(inputs.get("rates"))
    default_contract_type = inputs.get("contract_type")
    specs: list[dict] = []

    rate_material_names = {
        _pick_text(r, _MATERIAL_NAME_KEYS)
        for r in rates if isinstance(r, dict)
    } - {None}

    for quantity_item in quantities:
        if not isinstance(quantity_item, dict):
            material_name = _single_material_name_from(rates)
            specs.append({
                "material_name": material_name,
                "quantity": _to_number(quantity_item),
                "unit": None,
                "contract_type": default_contract_type,
                "source": "quantities",
            })
            continue

        material_name = _pick_text(quantity_item, _MATERIAL_NAME_KEYS)
        if material_name and material_name in rate_material_names:
            continue

        current_price = _pick_number(quantity_item, _CURRENT_PRICE_KEYS)
        contract_price = _pick_number(quantity_item, _CONTRACT_PRICE_KEYS)
        if not material_name and not current_price and not contract_price:
            continue

        specs.append({
            "material_name": material_name,
            "quantity": _pick_number(quantity_item, _QUANTITY_KEYS),
            "unit": _pick_text(quantity_item, _UNIT_KEYS),
            "current_unit_price": current_price,
            "contract_unit_price": contract_price,
            "contract_type": (
                quantity_item.get("contract_type")
                or quantity_item.get("계약유형")
                or default_contract_type
            ),
            "is_market_sensitive": _pick_bool(quantity_item, _MARKET_SENSITIVE_KEYS),
            "vat_included": _pick_bool(quantity_item, _VAT_INCLUDED_KEYS),
            "source": "quantities",
        })

    return specs


def _dedupe_specs(specs: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    seen = set()
    for spec in specs:
        key = (
            spec.get("material_name"),
            spec.get("quantity"),
            spec.get("unit"),
            spec.get("current_unit_price"),
            spec.get("contract_unit_price"),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(spec)
    return deduped


def _collect_specs(inputs: dict) -> list[dict]:
    specs = _specs_from_rates(inputs)
    specs.extend(_specs_from_quantities(inputs))
    return _dedupe_specs(specs)


# ── 단가 조회 / 보조 ───────────────────────────────────────────────────────────

def _price_from_db(material_name: str) -> tuple[dict | None, str | None]:
    last_message = None
    for candidate in _material_lookup_candidates(material_name):
        lookup = _search_material_price_core(candidate)
        if lookup.get("status") == "success" and lookup.get("results"):
            return lookup["results"][0], None
        last_message = lookup.get("message")
    return None, last_message or f"자재 단가를 찾지 못했습니다: {material_name}"


def _fill_price_from_db(spec: dict, result: dict) -> bool:
    if spec.get("current_unit_price") is not None:
        return True

    material_name = spec.get("material_name")
    if not material_name:
        return False

    try:
        price_row, message = _price_from_db(material_name)
    except Exception as exc:
        spec["_db_error"] = str(exc)
        return False

    if price_row is None:
        spec["_not_found"] = message
        return False

    spec["material_name"] = price_row.get("자재명") or material_name
    spec["current_unit_price"] = _to_number(price_row.get("현재단가_원"))
    spec["unit"] = spec.get("unit") or price_row.get("단위")
    spec["is_market_sensitive"] = bool(price_row.get("시황성자재"))
    spec["vat_included"] = str(price_row.get("부가세여부") or "").strip() == "부가가치세포함"
    result["evidence"].append({
        "source": "material_prices",
        "type": "procurement_db",
        "content": (
            f"{spec['material_name']}: {spec['current_unit_price']:,.0f}원/"
            f"{spec.get('unit') or '-'}"
        ),
        "usage": "현재 자재 단가 적용",
    })
    return spec.get("current_unit_price") is not None


def _parse_contract_price_payload(raw: Any) -> dict | None:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = json.loads(raw)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _select_contract_price_from_payload(payload: dict) -> dict | None:
    projects = payload.get("공사별_계약단가")
    if not isinstance(projects, list):
        return None

    candidates: list[dict] = []
    for project in projects:
        if not isinstance(project, dict):
            continue
        for price_item in _as_list(project.get("계약단가목록")):
            if not isinstance(price_item, dict):
                continue
            price = _to_number(price_item.get("단가"))
            if price is None:
                continue
            candidates.append({
                "price": price,
                "unit": price_item.get("단위"),
                "material_name": price_item.get("자재명"),
                "project_id": project.get("공사명"),
                "year": project.get("연도"),
                "doc_type": project.get("문서유형"),
                "file_name": project.get("출처파일"),
            })

    if not candidates:
        return None

    def _year_key(item: dict) -> int:
        try:
            return int(str(item.get("year") or "").strip())
        except ValueError:
            return -1

    return sorted(candidates, key=_year_key)[-1]


def _fill_contract_price_from_company_docs(spec: dict, result: dict) -> bool:
    if spec.get("contract_unit_price") is not None:
        return True
    if _search_contract_price_tool is None:
        result["warnings"].append(
            "사내 계약문서 RAG 도구를 사용할 수 없어 계약단가 보조 조회를 건너뛰었습니다."
        )
        return False

    material_name = spec.get("material_name")
    if not material_name:
        return False

    try:
        raw = _search_contract_price_tool.invoke({"material_name": material_name})
    except Exception as exc:
        result["warnings"].append(
            f"{material_name} 사내 계약문서 RAG 조회 중 오류가 발생했습니다: {exc}"
        )
        _log.exception("company_docs contract price lookup failed for %s", material_name)
        return False

    payload = _parse_contract_price_payload(raw)
    if not payload:
        result["warnings"].append(
            f"{material_name} 사내 계약문서 RAG 응답을 해석하지 못해 기존 자재비 계산 방식을 유지합니다."
        )
        return False

    if payload.get("status") != "success":
        message = payload.get("message") or "계약단가를 찾지 못했습니다."
        result["warnings"].append(
            f"{material_name} 사내 계약문서 RAG에서 계약단가를 찾지 못했습니다: {message}"
        )
        return False

    selected = _select_contract_price_from_payload(payload)
    if not selected:
        result["warnings"].append(
            f"{material_name} 사내 계약문서 RAG 결과에서 계약단가 숫자를 추출하지 못했습니다."
        )
        return False

    spec["contract_unit_price"] = selected["price"]
    if not spec.get("unit") and selected.get("unit"):
        spec["unit"] = selected["unit"]

    result["evidence"].append({
        "source": "rag.company_docs",
        "type": "contract_db",
        "content": (
            f"{selected.get('material_name') or material_name}: {selected['price']:,.0f}원/"
            f"{selected.get('unit') or spec.get('unit') or '-'}"
            f" | 공사명: {selected.get('project_id') or '-'}"
            f" | 연도: {selected.get('year') or '-'}"
            f" | 출처파일: {selected.get('file_name') or '-'}"
        ),
        "usage": "사내 계약문서 RAG 기반 계약단가 적용",
    })
    result["assumptions"].append(
        f"{material_name} 계약단가는 사용자 입력이 없어 사내 계약문서 RAG에서 검색된 최근 계약단가 "
        f"{selected['price']:,.0f}원을 적용했습니다."
    )
    return True


# ── cost_item 빌더 ─────────────────────────────────────────────────────────────

def _build_cost_item(spec: dict, calc: dict) -> dict:
    material_name = calc["자재명"]
    quantity = calc["추가물량"]
    unit = calc["단위"]
    contract_type = _normalize_contract_type(calc.get("계약유형"))
    settlement_basis = calc.get("settlement_basis")
    amount = calc["material_cost_krw"]

    unit_price = (
        calc.get("계약단가_원")
        if settlement_basis == "fixed_contract_price"
        else calc.get("현재단가_원")
    )

    return {
        "name": f"{material_name} 자재비",
        "category": "material",
        "material_name": material_name,
        "unit": unit,
        "quantity": quantity,
        "unit_price": unit_price,
        "contract_unit_price": calc.get("계약단가_원"),
        "amount": amount,
        "formula": calc.get("basis") or f"{unit_price:,.0f}원/{unit} × {quantity:g}{unit} = {amount:,}원",
        "contract_type": contract_type,
        "settlement_basis": settlement_basis,
    }


# ── missing input ──────────────────────────────────────────────────────────────

def _missing_input_result(inputs: dict) -> dict:
    result = _base_result("MISSING_INFO", "자재비 계산에 필요한 구조화 입력이 부족합니다.")
    for field in _as_list(inputs.get("missing_fields")):
        _append_unique(result["missing_fields"], field)
    for field in ("material_name", "quantity", "current_unit_price"):
        _append_unique(result["missing_fields"], field)
    result["warnings"].append(
        "quantities 또는 rates에 material_name, quantity, current_unit_price 조합을 구조적으로 제공해야 합니다."
    )
    return result


# ── 핵심 계산 ──────────────────────────────────────────────────────────────────

def _calculate_result(inputs: dict) -> dict:
    specs = _collect_specs(inputs)
    if not specs:
        return _missing_input_result(inputs)

    result = _base_result("CALCULATED", "자재비를 계산했습니다.")
    result["assumptions"].append(
        "사용자 입력값을 우선 적용하고, 계약단가가 없을 때만 사내 계약문서 RAG를 보조 조회합니다."
    )

    failed_specs = 0
    db_errors = 0
    total_items_for_core: list[dict] = []

    for spec in specs:
        material_name = spec.get("material_name")
        quantity = _to_number(spec.get("quantity"))
        unit = spec.get("unit") or "단위"
        contract_type = _normalize_contract_type(spec.get("contract_type"))

        if not material_name:
            failed_specs += 1
            _append_unique(result["missing_fields"], "material_name")
            result["warnings"].append("자재명이 없는 입력 항목은 계산에서 제외했습니다.")
            continue
        if quantity is None:
            failed_specs += 1
            _append_unique(result["missing_fields"], f"{material_name}: quantity")
            result["warnings"].append(f"{material_name} 항목에 수량이 없어 계산에서 제외했습니다.")
            continue

        if not _fill_price_from_db(spec, result):
            failed_specs += 1
            if spec.get("_db_error"):
                db_errors += 1
                _append_unique(result["missing_fields"], f"{material_name}: current_unit_price")
                result["warnings"].append(
                    f"{material_name} 자재 단가 DB 조회 중 오류가 발생했습니다: {spec['_db_error']}"
                )
            else:
                _append_unique(result["missing_fields"], f"{material_name}: current_unit_price")
                result["warnings"].append(
                    spec.get("_not_found") or f"{material_name} 현재단가가 없어 계산에서 제외했습니다."
                )
            continue

        current_unit_price = _to_number(spec.get("current_unit_price"))
        contract_unit_price = _to_number(spec.get("contract_unit_price"))
        if current_unit_price is None:
            failed_specs += 1
            _append_unique(result["missing_fields"], f"{material_name}: current_unit_price")
            result["warnings"].append(
                f"{material_name} 현재단가가 숫자가 아니어서 계산에서 제외했습니다."
            )
            continue

        if contract_unit_price is None:
            _fill_contract_price_from_company_docs(spec, result)
            contract_unit_price = _to_number(spec.get("contract_unit_price"))

        if (
            contract_type == "고정단가"
            and contract_unit_price is None
            and spec.get("contract_unit_price") is not None
        ):
            result["warnings"].append(
                f"{material_name} 계약단가가 숫자가 아니어서 현재단가 기준으로 계산합니다."
            )

        calc = _calculate_quantity_change_cost_core(
            material_name=material_name,
            quantity=float(quantity),
            unit=str(unit),
            current_unit_price=float(current_unit_price),
            contract_unit_price=float(contract_unit_price) if contract_unit_price is not None else None,
            is_market_sensitive=bool(spec.get("is_market_sensitive")),
            contract_type=contract_type,
            vat_included=bool(spec.get("vat_included")),
        )

        if calc.get("status") != "success":
            failed_specs += 1
            _append_unique(result["missing_fields"], f"{material_name}: calculation")
            result["warnings"].append(f"{material_name} 자재비 계산에 실패했습니다.")
            continue

        result["cost_items"].append(_build_cost_item(spec, calc))
        result["warnings"].extend(calc.get("주의사항") or [])
        if calc.get("price_diff_reference_krw"):
            result["assumptions"].append(
                f"[참고 차액] {material_name}: {calc['price_diff_reference_krw']:,}원 "
                f"({contract_type} 계약 기준, total_cost 미반영 여부는 settlement_basis에 따름)"
            )
        if spec.get("current_unit_price") is not None and not any(
            e.get("usage") == "현재 자재 단가 적용" and material_name in e.get("content", "")
            for e in result["evidence"]
        ):
            result["evidence"].append({
                "source": "user_input",
                "type": "default_rule",
                "content": f"{material_name}: {current_unit_price:,.0f}원/{unit}",
                "usage": "사용자 제공 현재단가 적용",
            })
        if contract_unit_price is not None and not any(
            e.get("usage") == "사내 계약문서 RAG 기반 계약단가 적용"
            and material_name in e.get("content", "")
            for e in result["evidence"]
        ):
            result["evidence"].append({
                "source": "user_input",
                "type": "contract_db",
                "content": f"{material_name}: {contract_unit_price:,.0f}원/{unit}",
                "usage": "계약단가 적용",
            })
        total_items_for_core.append({
            "자재명": material_name,
            "추가비용_원": calc["material_cost_krw"],
            "단가기준": calc.get("settlement_basis") or "unknown",
        })

    if result["cost_items"]:
        total = _calculate_total_material_cost_core(total_items_for_core)
        result["total_cost"] = total["총_추가자재비_원"]
    else:
        result["total_cost"] = 0

    if result["cost_items"] and failed_specs:
        result["status"] = "PARTIAL"
        result["summary"] = "일부 자재비만 계산했습니다."
    elif result["cost_items"]:
        result["status"] = "CALCULATED"
        result["summary"] = f"자재비 {result['total_cost']:,}원을 계산했습니다."
    elif db_errors and failed_specs == len(specs):
        result["status"] = "ERROR"
        result["summary"] = "자재 단가 DB 조회 오류로 자재비를 계산하지 못했습니다."
    else:
        result["status"] = "MISSING_INFO"
        result["summary"] = "자재명, 수량 또는 단가 부족으로 자재비를 계산하지 못했습니다."

    return result


# ── 공개 API ───────────────────────────────────────────────────────────────────

def calculate_material_cost(inputs: dict | None) -> dict:
    """자재비 계산 진입점.

    Args:
        inputs: extractor_node가 생성한 state['inputs'] dict.
                None 또는 비-dict 인 경우 MISSING_INFO 결과를 반환한다.

    Returns:
        aggregator 계약(material_result schema)을 만족하는 result dict.
    """
    if not isinstance(inputs, dict):
        result = _base_result("MISSING_INFO", "자재비 계산 입력이 구조화 dict가 아닙니다.")
        result["missing_fields"].append("inputs")
        result["warnings"].append("extractor_node가 생성한 state['inputs'] dict가 필요합니다.")
        return result
    return _calculate_result(inputs)

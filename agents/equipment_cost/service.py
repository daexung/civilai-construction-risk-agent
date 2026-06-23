"""Equipment cost calculation service.

도메인 계산 로직의 단일 진입점.
agents/router/nodes/equipment_node.py 는 이 모듈을 호출하는 얇은 adapter 역할만 한다.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from agents.equipment_cost.tools import (
    _get_equipment_by_work_type_core,
    _get_equipment_rental_rate_core,
    _calculate_standby_cost_core,
)

_log = logging.getLogger(__name__)

# ── 상수 ───────────────────────────────────────────────────────────────────────
_EXCLUDED_ITEMS = ["인건비", "자재비", "이윤", "부가세"]
_STATUS_VALUES = {"CALCULATED", "MISSING_INFO", "PARTIAL", "ERROR"}

_EQUIP_NAME_KEYS = ("equipment_type", "equipment_name", "equipment", "machine_type")
_DAILY_RATE_KEYS = ("daily_rental_rate", "unit_price")
_STANDBY_RATE_KEYS = ("standby_rate",)
_DELAY_KEYS = ("delay_days", "standby_days", "duration_days")
_COUNT_KEYS = ("quantity", "count", "units")

_STRONG_EQUIP_KEYS = frozenset({
    "equipment_type", "equipment_name", "equipment", "machine_type",
    "daily_rental_rate", "standby_rate", "standby_days",
})

_EQUIP_NAME_ALIASES: dict[str, str] = {
    "펌프카":         "콘크리트 펌프차",
    "콘크리트펌프":   "콘크리트 펌프차",
    "콘크리트펌프카": "콘크리트 펌프차",
    "펌프트럭":       "콘크리트 펌프차",
    "믹서트럭":       "콘크리트 믹서트럭",
    "레미콘트럭":     "콘크리트 믹서트럭",
    "콘크리트믹서":   "콘크리트 믹서트럭",
    "타이어크레인":   "크레인(타이어)",
    "무한궤도크레인": "크레인(무한궤도)",
    "트럭크레인":     "트럭탑재형크레인",
    "카고크레인":     "트럭탑재형크레인",
}


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
        s = value.strip()
        is_pct = s.endswith("%")
        cleaned = s.replace(",", "").replace("원", "").replace("일", "").replace("%", "").strip()
        if not cleaned:
            return None
        try:
            v = float(cleaned)
            return v / 100.0 if is_pct else v
        except ValueError:
            return None
    return None


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


def _is_equipment_rate(source: dict) -> bool:
    """자재/노무 전용 항목을 equipment 후보에서 제외한다."""
    if not isinstance(source, dict):
        return False
    return any(k in source and source.get(k) is not None for k in _STRONG_EQUIP_KEYS)


# ── 장비명 정규화 ──────────────────────────────────────────────────────────────

def _resolve_equipment_name(name: str) -> str:
    """사용자 입력 장비명을 DB 장비명으로 정규화한다. 매핑 없으면 원본 반환."""
    compact = re.sub(r"\s+", "", name)
    for alias, canonical in _EQUIP_NAME_ALIASES.items():
        if alias in compact:
            return canonical
    return name


def _lookup_equipment_item_core(equipment_type_db: str, spec_hint: str | None) -> dict | None:
    """DB에서 장비 항목 1개 선택.

    spec_hint 숫자로 규격 매칭 → is_standard 우선 → 첫 번째.
    반환: {"equipment_type", "spec", "daily_rental_rate", "standby_rate", "is_standard"} 또는 None.
    """
    try:
        core = _get_equipment_rental_rate_core(equipment_type_db)
    except Exception:
        return None
    if not core.get("found"):
        return None
    items = core.get("items") or []
    if not items:
        return None

    if spec_hint:
        nums = re.findall(r"\d+", str(spec_hint))
        if nums:
            matched = [i for i in items if any(n in str(i.get("spec") or "") for n in nums)]
            if matched:
                std_matched = [i for i in matched if i.get("is_standard")]
                return (std_matched or matched)[0]

    std = [i for i in items if i.get("is_standard")]
    return (std or items)[0]


# ── 결과 구조 ──────────────────────────────────────────────────────────────────

def _base_result(status: str, summary: str) -> dict:
    return {
        "agent_name": "equipment",
        "domain": "equipment",
        "main_cause": "equipment",
        "is_relevant": True,
        "status": status if status in _STATUS_VALUES else "ERROR",
        "summary": summary,
        "cost_items": [],
        "total_cost": 0,
        "missing_fields": [],
        "warnings": [],
        "assumptions": ["장비 대기비는 조종원 인건비 제외 기준"],
        "excluded_items": list(_EXCLUDED_ITEMS),
        "evidence": [],
    }


# ── cost_item 빌더 ─────────────────────────────────────────────────────────────

def _zero_item(name: str) -> dict:
    return {
        "category": "equipment",
        "name": name,
        "spec": "",
        "quantity": 1,
        "days": 0.0,
        "daily_rate": None,
        "standby_rate": None,
        "amount": 0,
        "description": "장비 대기 없음 (0일 명시)",
    }


def _build_standby_item(name: str, spec_str: str | None, qty: float, calc: dict) -> dict:
    return {
        "category": "equipment",
        "name": name,
        "spec": spec_str or "",
        "quantity": qty,
        "days": calc["delay_days"],
        "daily_rate": calc["daily_rental_rate"],
        "standby_rate": calc["standby_rate"],
        "amount": int(calc["total"] * qty),
        "description": (
            f"{name}: {calc['daily_rental_rate']:,}원/일 × {calc['standby_rate']} × {calc['delay_days']}일"
            + (f" × {qty:g}대" if qty > 1 else "")
        ),
    }


def _build_range_item(name: str, qty: float, core: dict, delay_days: float) -> dict:
    std = core.get("standard") or {}
    return {
        "category": "equipment",
        "name": name,
        "spec": std.get("spec") or "(표준 규격)",
        "quantity": qty,
        "days": delay_days,
        "daily_rate": std.get("daily_rental_rate"),
        "standby_rate": core.get("standby_rate"),
        "amount": int((std.get("standby_cost") or 0) * qty),
        "description": (
            f"{name} 표준 규격 {core.get('std_note', '')}: "
            f"{std.get('daily_rental_rate', 0):,}원/일 × {core.get('standby_rate', 0)} × {delay_days}일"
            + (f" × {qty:g}대" if qty > 1 else "")
        ),
    }


# ── delay_days 추출 ─────────────────────────────────────────────────────────────

def _parse_weather_delay(weather_val: Any) -> float | None:
    """weather_result / weather_response dict에서 delay_days를 추출한다."""
    if isinstance(weather_val, str):
        try:
            weather_val = json.loads(weather_val)
        except Exception:
            return None
    if not isinstance(weather_val, dict):
        return None
    risk = weather_val.get("risk_result") or weather_val.get("risk") or {}
    if not isinstance(risk, dict):
        return None
    policy = risk.get("delay_policy") or {}
    if isinstance(policy, dict):
        policy_type = str(policy.get("type") or "").upper()
        if policy_type == "FULL_DAY":
            d = _to_number(policy.get("minimum_delay_days"))
            if d is not None:
                return d
        elif policy_type == "PROPORTIONAL":
            d = _to_number(risk.get("delay_day_equivalent"))
            if d is not None:
                return d
    for key in ("delay_day_equivalent", "delay_days", "standby_days"):
        d = _to_number(risk.get(key))
        if d is not None:
            return d
    return None


def _extract_global_delay(state: dict, inputs: dict) -> float | None:
    """inputs.duration_days → weather 순서로 전역 delay_days를 찾는다."""
    d = _to_number(inputs.get("duration_days"))
    if d is not None:
        return d
    for key in ("weather_result", "weather_response"):
        d = _parse_weather_delay(state.get(key))
        if d is not None:
            return d
    return None


def _extract_work_type(inputs: dict) -> str | None:
    wt = inputs.get("work_type")
    if isinstance(wt, str) and wt.strip():
        return wt.strip()
    if isinstance(wt, dict):
        return _pick_text(wt, ("raw_text", "name", "type", "category"))
    return None


def _extract_equipment_specs(inputs: dict) -> list[dict]:
    """inputs.rates에서 equipment 항목만 추출한다."""
    specs = []
    for rate in _as_list(inputs.get("rates")):
        if not _is_equipment_rate(rate):
            continue
        specs.append({
            "equipment_name":    _pick_text(rate, _EQUIP_NAME_KEYS),
            "spec":              _pick_text(rate, ("spec",)),
            "daily_rental_rate": _pick_number(rate, _DAILY_RATE_KEYS),
            "standby_rate":      _pick_number(rate, _STANDBY_RATE_KEYS),
            "delay_days":        _pick_number(rate, _DELAY_KEYS),
            "quantity":          _pick_number(rate, _COUNT_KEYS) or 1.0,
        })
    return specs


# ── 핵심 계산 ──────────────────────────────────────────────────────────────────

def _calculate_result(state: dict, inputs: dict) -> dict:
    result = _base_result("CALCULATED", "")
    result["assumptions"].append("입력된 장비 정보만 사용했으며 누락 값은 추정하지 않았습니다.")

    global_delay = _extract_global_delay(state, inputs)
    equipment_specs = _extract_equipment_specs(inputs)
    work_type = _extract_work_type(inputs)
    failed_specs = 0
    db_errors = 0

    # ── 경로 1: rates에서 추출한 장비 spec별 계산 ──────────────────────────────
    if equipment_specs:
        for spec in equipment_specs:
            eq_name = spec.get("equipment_name") or "장비"
            qty = spec.get("quantity") or 1.0
            item_delay = spec.get("delay_days")
            delay_days = item_delay if item_delay is not None else global_delay
            daily_rate = spec.get("daily_rental_rate")
            standby_rate = spec.get("standby_rate")

            if delay_days is not None and float(delay_days) == 0.0:
                result["cost_items"].append(_zero_item(eq_name))
                _append_unique(result["assumptions"], "사용자 명시 기준으로 장비 대기비 없음/0원 처리")
                continue

            if delay_days is None:
                failed_specs += 1
                _append_unique(result["missing_fields"], f"{eq_name}: delay_days")
                result["warnings"].append(f"'{eq_name}' 항목에 대기 일수(delay_days)가 없습니다.")
                continue

            # Case A: daily_rental_rate + standby_rate 모두 있으면 직접 계산
            if daily_rate is not None and standby_rate is not None:
                try:
                    calc = _calculate_standby_cost_core(int(daily_rate), float(standby_rate), float(delay_days))
                    result["cost_items"].append(_build_standby_item(eq_name, spec.get("spec"), qty, calc))
                    result["evidence"].append({
                        "source": "user_input",
                        "type": "equipment_db",
                        "content": f"{eq_name}: {int(daily_rate):,}원/일 × {standby_rate} × {delay_days}일",
                        "usage": "사용자 제공 단가·요율 적용",
                    })
                except Exception as exc:
                    failed_specs += 1
                    result["warnings"].append(f"'{eq_name}' 대기비 계산 중 오류: {exc}")
                    _log.exception("standby cost calc failed for %s", eq_name)
                continue

            # Case B: DB 조회 — spec 우선 매칭 → is_standard 폴백
            eq_name_db = _resolve_equipment_name(eq_name)
            eq_spec_hint = spec.get("spec")
            try:
                db_item = _lookup_equipment_item_core(eq_name_db, eq_spec_hint)
            except Exception as exc:
                failed_specs += 1
                db_errors += 1
                _append_unique(result["missing_fields"], f"{eq_name}: rental_rate")
                result["warnings"].append(f"'{eq_name_db}' DB 조회 중 오류: {exc}")
                _log.exception("equipment cost range lookup failed for %s", eq_name_db)
                continue

            if db_item is None:
                failed_specs += 1
                _append_unique(result["missing_fields"], f"{eq_name}: rental_rate")
                result["warnings"].append(f"장비 임대단가 DB에서 '{eq_name_db}'을 찾지 못했습니다.")
                continue

            applied_spec = db_item.get("spec") or "(기본)"
            if eq_spec_hint and str(eq_spec_hint) not in str(applied_spec):
                spec_label = "표준 규격" if db_item.get("is_standard") else "유사 규격"
                result["warnings"].append(
                    f"'{eq_name}' 규격 {eq_spec_hint!r}와 정확히 일치하는 DB 항목 없음 → "
                    f"{spec_label} {applied_spec!r} 적용. 정확도 향상을 위해 규격 확인 권장."
                )

            try:
                calc = _calculate_standby_cost_core(
                    int(db_item["daily_rental_rate"]),
                    float(db_item["standby_rate"]),
                    float(delay_days),
                )
                result["cost_items"].append(_build_standby_item(eq_name, applied_spec, qty, calc))
                result["evidence"].append({
                    "source": "equipment_cost.equipment_rental",
                    "type": "equipment_db",
                    "content": (
                        f"{eq_name_db} ({applied_spec}): "
                        f"{int(db_item['daily_rental_rate']):,}원/일 × {db_item['standby_rate']}"
                        f" × {delay_days}일"
                    ),
                    "usage": f"DB {'규격 매칭' if eq_spec_hint else '표준'} 단가 적용",
                })
            except Exception as exc:
                failed_specs += 1
                result["warnings"].append(f"'{eq_name}' 대기비 계산 중 오류: {exc}")
                _log.exception("standby cost calc failed for %s", eq_name)

    # ── 경로 2: work_type 기반 장비 자동 탐색 ─────────────────────────────────
    elif work_type:
        if global_delay is None:
            for rate in _as_list(inputs.get("rates")):
                d = _pick_number(rate, _DELAY_KEYS)
                if d is not None:
                    global_delay = d
                    _log.info("Path 2: rates에서 delay_days=%s 확보", global_delay)
                    break

        if global_delay is None:
            failed_specs += 1
            _append_unique(result["missing_fields"], "delay_days")
            result["warnings"].append(
                f"공종 '{work_type}'을 확인했으나 대기 일수(delay_days)가 없어 대기비를 계산할 수 없습니다."
            )
        elif float(global_delay) == 0.0:
            result["cost_items"].append(_zero_item(f"{work_type} 장비"))
            _append_unique(result["assumptions"], "사용자 명시 기준으로 장비 대기비 없음/0원 처리")
        else:
            try:
                wt_core = _get_equipment_by_work_type_core(work_type)
            except Exception as exc:
                failed_specs += 1
                db_errors += 1
                result["warnings"].append(f"공종별 장비 DB 조회 중 오류: {exc}")
                _log.exception("equipment by work type lookup failed for %s", work_type)
                wt_core = {"found": False}

            if not wt_core.get("found"):
                failed_specs += 1
                _append_unique(result["missing_fields"], "equipment_type")
                result["warnings"].append(
                    f"공종 '{work_type}'에 해당하는 장비를 DB에서 찾지 못했습니다. "
                    "equipment_type을 직접 지정해 주세요."
                )
            else:
                items = wt_core.get("items") or []
                primary = [i for i in items if i.get("priority") == "주요"]
                std_primary = [i for i in primary if i.get("is_standard")]
                selected_eq = (std_primary or primary or [None])[0]

                if selected_eq is None:
                    failed_specs += 1
                    _append_unique(result["missing_fields"], "equipment_type")
                    result["warnings"].append(
                        f"공종 '{work_type}'에 사용 가능한 주요 장비를 DB에서 찾지 못했습니다."
                    )
                else:
                    eq = selected_eq
                    calc = _calculate_standby_cost_core(
                        int(eq["daily_rental_rate"]),
                        float(eq["standby_rate"]),
                        float(global_delay),
                    )
                    result["cost_items"].append(
                        _build_standby_item(eq["equipment_type"], eq.get("spec"), 1.0, calc)
                    )
                    result["evidence"].append({
                        "source": "equipment_cost.equipment_rental",
                        "type": "equipment_db",
                        "content": (
                            f"{work_type} 공종 표준 장비: {eq['equipment_type']} / {eq.get('spec', '')}"
                            f" ({wt_core.get('year')} 기준)"
                        ),
                        "usage": "공종별 표준 장비 자동 선택 (is_standard 우선)",
                    })
                    other = [i for i in primary if i is not eq]
                    if other:
                        cand_str = ", ".join(
                            f"{i['equipment_type']}({i.get('spec', '')})" for i in other[:4]
                        )
                        result["warnings"].append(
                            f"'{work_type}' 공종 표준 장비 적용: {eq['equipment_type']} {eq.get('spec', '')}. "
                            f"다른 후보: {cand_str}"
                        )

    # ── 경로 3: 장비 정보 없음 ────────────────────────────────────────────────
    else:
        failed_specs += 1
        _append_unique(result["missing_fields"], "equipment_type")
        if global_delay is None:
            _append_unique(result["missing_fields"], "delay_days")
        result["warnings"].append(
            "장비 대기비 계산에 필요한 장비 정보(equipment_type 또는 rates)가 없습니다."
        )

    # ── 총액 및 상태 결정 ─────────────────────────────────────────────────────
    result["total_cost"] = sum(
        item["amount"] for item in result["cost_items"]
        if isinstance(item.get("amount"), (int, float))
    )

    if result["cost_items"] and failed_specs > 0:
        result["status"] = "PARTIAL"
        result["summary"] = "일부 장비 대기비만 계산했습니다."
    elif result["cost_items"]:
        result["status"] = "CALCULATED"
        result["summary"] = (
            "장비 대기비 없음으로 확인되었습니다."
            if result["total_cost"] == 0
            else f"장비 대기비 {result['total_cost']:,}원을 계산했습니다."
        )
    elif db_errors > 0:
        result["status"] = "ERROR"
        result["summary"] = "장비 임대단가 DB 조회 오류로 대기비를 계산하지 못했습니다."
    else:
        result["status"] = "MISSING_INFO"
        result["summary"] = "장비 종류, 임대단가 또는 대기 일수 정보가 부족합니다."

    for field in _as_list(inputs.get("missing_fields")):
        _append_unique(result["missing_fields"], field)

    return result


# ── 공개 API ───────────────────────────────────────────────────────────────────

def calculate_equipment_cost(state: dict, inputs: dict | None) -> dict:
    """장비 대기비 계산 진입점.

    Args:
        state:  LangGraph state dict. weather_result / weather_response 참조용.
        inputs: extractor_node가 생성한 state['inputs'] dict.
                None 또는 비-dict인 경우 MISSING_INFO 결과를 반환한다.

    Returns:
        aggregator 계약(equipment_result schema)을 만족하는 result dict.
    """
    if not isinstance(inputs, dict):
        result = _base_result("MISSING_INFO", "장비 대기비 계산 입력이 구조화 dict가 아닙니다.")
        result["missing_fields"].append("inputs")
        result["warnings"].append("extractor_node가 생성한 state['inputs'] dict가 필요합니다.")
        return result
    return _calculate_result(state, inputs)

"""Aggregate domain node results before final synthesis."""
from __future__ import annotations

import json
import re
from typing import Any

from logger import get_logger

log = get_logger(__name__)

# 입력은 현재 ReAct wrapper가 생성한 dict일 수 있다. 추후 도메인 노드를
# deterministic으로 전환해도 aggregator는 공통 result schema만 소비하므로
# 변경 불필요.

_DOMAIN_SOURCES = (
    ("weather", "weather_result", "weather_response"),
    ("labor_cost", "labor_cost_result", "labor_cost_response"),
    ("material", "material_result", "material_response"),
    ("equipment", "equipment_result", "equipment_response"),
)


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _clean_json_text(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.MULTILINE).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        return cleaned[start:end + 1]
    return cleaned


def _parse_json_response(value: Any) -> dict | None:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = json.loads(_clean_json_text(value))
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _coerce_result(state: dict, result_key: str, response_key: str) -> dict | None:
    result = state.get(result_key)
    parsed = _parse_json_response(result)
    if parsed is not None:
        return parsed
    return _parse_json_response(state.get(response_key))


def _append_unique(target: list, item: Any) -> None:
    if item in target:
        return
    target.append(item)


def _merge_list_field(aggregated: dict, field: str, items: Any, agent: str) -> None:
    for item in _as_list(items):
        if item is None:
            continue
        if field == "evidence" and isinstance(item, dict):
            value = {"agent": agent, **item}
        elif field in {"missing_fields", "warnings", "assumptions", "excluded_items"}:
            value = item
        else:
            value = {"agent": agent, "content": item}
        _append_unique(aggregated[field], value)


def _numeric_amount(value: Any) -> int | float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    return None


def _merge_cost_items(aggregated: dict, result: dict, agent: str) -> None:
    for item in _as_list(result.get("cost_items")):
        if isinstance(item, dict):
            cost_item = {"agent": agent, **item}
        else:
            cost_item = {"agent": agent, "item": item}
        aggregated["cost_items"].append(cost_item)

    for item in _as_list(result.get("calculation_details")):
        if isinstance(item, dict):
            detail = {"agent": agent, **item}
        else:
            detail = {"agent": agent, "detail": item}
        aggregated["calculation_details"].append(detail)


def _sum_cost_items(cost_items: list) -> int | float | None:
    amounts = [
        amount
        for amount in (_numeric_amount(item.get("amount")) for item in cost_items if isinstance(item, dict))
        if amount is not None
    ]
    return sum(amounts) if amounts else None


def _pick_main_cause(results: list[tuple[str, dict]]) -> Any:
    for _, result in results:
        for key in ("main_cause", "cause"):
            value = result.get(key)
            if value:
                return value
    return None


def _extract_weather_delay(weather_result: dict, aggregated: dict) -> None:
    risk = weather_result.get("risk_result") or weather_result.get("risk") or weather_result
    if not isinstance(risk, dict):
        return

    policy = risk.get("delay_policy") or {}
    if not isinstance(policy, dict):
        policy = {}

    policy_type = str(policy.get("type") or "").upper()
    delay_days = None
    if policy_type == "FULL_DAY":
        delay_days = policy.get("minimum_delay_days")
    elif policy_type == "PROPORTIONAL":
        delay_days = risk.get("delay_day_equivalent")

    if delay_days is not None:
        aggregated["summary"]["delay_days"] = delay_days
        aggregated["summary"]["expected_delay"] = delay_days
        aggregated["weather"]["delay_policy"] = policy
        aggregated["weather"]["delay_day_equivalent"] = risk.get("delay_day_equivalent")
        aggregated["assumptions"].append(
            "기상 분석 기반 delay_days는 권고/가정 값이며 확정 지연일이 아닙니다."
        )

    for source_key, target_key in (
        ("risk_level", "risk_level"),
        ("work_stoppage_required", "work_stoppage_required"),
    ):
        if risk.get(source_key) is not None:
            aggregated["weather"][target_key] = risk.get(source_key)

    if aggregated["summary"].get("risk_level") is None and risk.get("risk_level") is not None:
        aggregated["summary"]["risk_level"] = risk.get("risk_level")


def _put_if_present(target: dict, target_key: str, source: dict, source_key: str) -> None:
    if source_key in source and source.get(source_key) is not None:
        target[target_key] = source.get(source_key)


def _extract_weather_summary(weather_result: dict, aggregated: dict) -> None:
    site = weather_result.get("site") if isinstance(weather_result.get("site"), dict) else {}
    work = weather_result.get("work") if isinstance(weather_result.get("work"), dict) else {}
    summary = weather_result.get("summary") if isinstance(weather_result.get("summary"), dict) else {}
    forecast = weather_result.get("forecast") if isinstance(weather_result.get("forecast"), dict) else {}

    weather_summary: dict[str, Any] = {}
    _put_if_present(weather_summary, "site_name", site, "site_name")
    _put_if_present(weather_summary, "work_type", work, "work_type")
    _put_if_present(weather_summary, "max_pop_pct", summary, "max_pop_pct")
    _put_if_present(weather_summary, "total_pcp_mm", summary, "total_pcp_mm")
    _put_if_present(weather_summary, "min_tmp_c", summary, "min_tmp_c")
    _put_if_present(weather_summary, "max_wsd_mps", summary, "max_wsd_mps")
    _put_if_present(weather_summary, "has_precipitation", summary, "has_precipitation")
    _put_if_present(weather_summary, "forecast_source", forecast, "source")
    _put_if_present(weather_summary, "base_datetime", forecast, "base_datetime")

    for warning in _as_list(weather_result.get("warnings")):
        if "No forecasts" in str(warning):
            weather_summary["no_forecast_warning"] = str(warning)
            break

    if weather_summary:
        aggregated["weather_summary"] = weather_summary


def _merge_result(aggregated: dict, agent: str, result: dict) -> None:
    aggregated["domains"][agent] = result
    _merge_cost_items(aggregated, result, agent)

    for field in ("missing_fields", "warnings", "assumptions", "excluded_items", "evidence"):
        _merge_list_field(aggregated, field, result.get(field), agent)
    _merge_list_field(aggregated, "missing_fields", result.get("missing_info"), agent)

    total = _numeric_amount(result.get("total_cost"))
    if total is not None:
        aggregated["_domain_totals"].append(total)

    if aggregated["summary"].get("risk_level") is None and result.get("risk_level") is not None:
        aggregated["summary"]["risk_level"] = result.get("risk_level")
    if aggregated["summary"].get("expected_delay") is None:
        for key in ("expected_delay", "delay_days"):
            if result.get(key) is not None:
                aggregated["summary"]["expected_delay"] = result.get(key)
                break


def aggregator_node(state: dict) -> dict:
    log.debug("aggregator_node entered")
    aggregated = {
        "cost_items": [],
        "calculation_details": [],
        "total_cost": None,
        "missing_fields": [],
        "warnings": [],
        "assumptions": [],
        "excluded_items": [],
        "evidence": [],
        "main_cause": None,
        "summary": {
            "total_additional_cost": None,
            "risk_level": None,
            "expected_delay": None,
            "delay_days": None,
            "main_cause": None,
        },
        "weather": {},
        "domains": {},
        "_domain_totals": [],
    }

    collected: list[tuple[str, dict]] = []
    for agent, result_key, response_key in _DOMAIN_SOURCES:
        result = _coerce_result(state, result_key, response_key)
        if result is None:
            continue
        collected.append((agent, result))
        _merge_result(aggregated, agent, result)
        if agent == "weather":
            _extract_weather_delay(result, aggregated)
            _extract_weather_summary(result, aggregated)

    eq_raw = state.get("equipment_result") or {}
    if isinstance(eq_raw, str):
        try:
            import json as _json
            eq_raw = _json.loads(eq_raw)
        except Exception:
            eq_raw = {}
    print(
        f'[집계기] equipment_result: status={eq_raw.get("status")}'
        f'  cost_items={len(eq_raw.get("cost_items") or [])}'
        f'  missing_fields={eq_raw.get("missing_fields")}'
    )
    print(f'[집계기] aggregated.cost_items 최종={len(aggregated["cost_items"])}개')

    for field in _as_list(state.get("missing_for_cost")):
        _append_unique(aggregated["missing_fields"], field)

    for field in _as_list((state.get("inputs") or {}).get("missing_fields")):
        _append_unique(aggregated["missing_fields"], field)

    item_total = _sum_cost_items(aggregated["cost_items"])
    domain_total = sum(aggregated["_domain_totals"]) if aggregated["_domain_totals"] else None
    total_cost = item_total if item_total is not None else domain_total
    aggregated["total_cost"] = total_cost
    aggregated["summary"]["total_additional_cost"] = total_cost

    # 순수 비용 계산이 완료된 경우 non-blocking missing field를 제거한다.
    # 계산에 쓰이지 않았지만 extractor가 기계적으로 추가하는 필드들:
    #   location     — 자재/장비/인건비 계산에 불필요
    #   material_name — 계산 완료 후에는 already-used 정보라 blocking이 아님
    # weather 분석이 필요한 경우(needs_weather=True)에는 location을 유지한다.
    _NON_BLOCKING_COST_FIELDS = {"location", "material_name", "자재명"}
    if not state.get("needs_weather") and aggregated["cost_items"]:
        aggregated["missing_fields"] = [
            f for f in aggregated["missing_fields"]
            if f not in _NON_BLOCKING_COST_FIELDS
        ]

    main_cause = _pick_main_cause(collected)
    aggregated["main_cause"] = main_cause
    aggregated["summary"]["main_cause"] = main_cause

    requested_agents = state.get("target_agents") or []
    missing_cost_agents = [
        agent for agent in requested_agents
        if agent in {"labor_cost", "material", "equipment"} and agent not in aggregated["domains"]
    ]
    if missing_cost_agents:
        aggregated["warnings"].append(
            f"요청된 비용 도메인 결과가 누락되었습니다: {', '.join(missing_cost_agents)}"
        )
    if requested_agents and not aggregated["cost_items"]:
        aggregated["warnings"].append(
            "비용 도메인에서 확정 cost_items가 생성되지 않았습니다. 최종 합성 노드는 사용자 입력으로 별도 계산하지 않습니다."
        )

    aggregated.pop("_domain_totals", None)
    log.info("aggregator_node completed")
    return {"aggregated_result": aggregated}

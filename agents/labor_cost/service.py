"""Labor cost calculation service.

도메인 계산 로직의 단일 진입점.
agents/router/nodes/labor_cost_node.py 는 이 모듈을 호출하는 얇은 adapter 역할만 한다.
"""
from __future__ import annotations

import logging
import math
import re
from typing import Any

from agents.labor_cost.tools import (
    _get_labor_price_core,
    _search_standard_spec_core,
    _calculate_workers_core,
    _calculate_labor_cost_core,
    _search_membrane_waterproofing_by_keyword_core,
)

_log = logging.getLogger(__name__)

# ── 상수 ───────────────────────────────────────────────────────────────────────
_EXCLUDED_ITEMS = ["장비비", "자재비", "이윤", "부가세", "도심지 할증"]
_STATUS_VALUES = {"CALCULATED", "MISSING_INFO", "PARTIAL", "ERROR"}

_JOB_TYPE_KEYS = (
    "job_type", "labor_type", "trade", "role", "worker_type",
    "occupation", "name", "직종", "type",
)
_WORKER_KEYS = (
    "workers", "worker_count", "man_days", "man_day", "total_workers",
    "labor_count", "count", "인원",
)
_DURATION_KEYS = ("duration_days", "days", "duration", "일수")
_QUANTITY_KEYS = ("quantity", "qty", "amount_quantity", "수량", "물량")
_UNIT_LABOR_KEYS = ("unit_labor", "labor_unit", "labor_rate", "man_day_per_unit", "품량")
_MATERIAL_RATE_KEYS = (
    "material_name", "material", "item_name",
    "current_unit_price", "current_price", "contract_unit_price", "contract_price",
    "unit_price", "현재단가", "계약단가", "자재명", "품목",
)


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
        cleaned = value.strip().replace(",", "")
        if not cleaned:
            return None
        try:
            return float(cleaned)
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


def _has_any_key(source: dict, keys: tuple[str, ...]) -> bool:
    return any(key in source and source.get(key) is not None for key in keys)


def _is_unrelated_material_rate(source: dict) -> bool:
    has_labor_identity = _pick_text(source, _JOB_TYPE_KEYS) is not None
    has_labor_rate = _pick_number(source, _UNIT_LABOR_KEYS) is not None
    has_worker_value = _pick_number(source, _WORKER_KEYS) is not None
    has_material_marker = _has_any_key(source, _MATERIAL_RATE_KEYS)
    return has_material_marker and not (has_labor_identity or has_labor_rate or has_worker_value)


# ── 결과 구조 ──────────────────────────────────────────────────────────────────

def _base_result(status: str, summary: str) -> dict:
    return {
        "agent_name": "labor",
        "domain": "인건비",
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
        "main_cause": "labor_cost",
    }


# ── spec 수집 ──────────────────────────────────────────────────────────────────

def _quantity_value(item: Any) -> float | None:
    if isinstance(item, dict):
        return _pick_number(item, _QUANTITY_KEYS)
    return _to_number(item)


def _quantity_by_job(quantities: list, job_type: str | None) -> float | None:
    if not quantities:
        return None
    if job_type:
        for item in quantities:
            if not isinstance(item, dict):
                continue
            item_job = _pick_text(item, _JOB_TYPE_KEYS)
            if item_job and item_job == job_type:
                return _quantity_value(item)
    if len(quantities) == 1:
        return _quantity_value(quantities[0])
    return None


def _single_job_type_from(items: list) -> str | None:
    jobs = []
    for item in items:
        if isinstance(item, dict):
            job_type = _pick_text(item, _JOB_TYPE_KEYS)
            if job_type and job_type not in jobs:
                jobs.append(job_type)
    return jobs[0] if len(jobs) == 1 else None


def _specs_from_workers(inputs: dict, warnings: list) -> list[dict]:
    workers = inputs.get("workers")
    duration_days = _to_number(inputs.get("duration_days"))
    rates = _as_list(inputs.get("rates"))
    quantities = _as_list(inputs.get("quantities"))
    specs: list[dict] = []

    if workers is None:
        return specs

    if isinstance(workers, dict):
        worker_items = workers.get("items") if isinstance(workers.get("items"), list) else [workers]
    elif isinstance(workers, list):
        worker_items = workers
    else:
        job_type = _single_job_type_from(rates) or _single_job_type_from(quantities)
        worker_count = _to_number(workers)
        if worker_count is None:
            warnings.append("workers 값이 숫자 또는 직종별 구조가 아니어서 인건비를 계산하지 않았습니다.")
            return specs
        specs.append({"job_type": job_type, "workers": worker_count, "source": "workers"})
        return specs

    for item in worker_items:
        if not isinstance(item, dict):
            worker_count = _to_number(item)
            if worker_count is not None:
                specs.append({"job_type": None, "workers": worker_count, "source": "workers"})
            continue

        job_type = _pick_text(item, _JOB_TYPE_KEYS)
        explicit_workers = _pick_number(item, ("man_days", "man_day", "total_workers"))
        if explicit_workers is None:
            worker_count = _pick_number(item, _WORKER_KEYS)
            item_duration = _pick_number(item, _DURATION_KEYS)
            if item_duration is None:
                item_duration = duration_days
            explicit_workers = (
                worker_count * item_duration
                if worker_count is not None and item_duration
                else worker_count
            )

        specs.append({"job_type": job_type, "workers": explicit_workers, "source": "workers"})

    return specs


def _specs_from_rates_and_quantities(inputs: dict) -> list[dict]:
    rates = _as_list(inputs.get("rates"))
    quantities = _as_list(inputs.get("quantities"))
    specs: list[dict] = []

    for rate in rates:
        if not isinstance(rate, dict):
            continue
        if _is_unrelated_material_rate(rate):
            continue

        job_type = _pick_text(rate, _JOB_TYPE_KEYS)
        unit_labor = _pick_number(rate, _UNIT_LABOR_KEYS)
        quantity = _pick_number(rate, _QUANTITY_KEYS)
        if quantity is None:
            quantity = _quantity_by_job(quantities, job_type)

        if job_type or unit_labor is not None or quantity is not None:
            specs.append({
                "job_type": job_type,
                "unit_labor": unit_labor,
                "quantity": quantity,
                "source": "rates",
            })

    return specs


def _dedupe_specs(specs: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    seen = set()
    for spec in specs:
        key = (
            spec.get("job_type"),
            spec.get("workers"),
            spec.get("quantity"),
            spec.get("unit_labor"),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(spec)
    return deduped


def _collect_specs(inputs: dict, warnings: list) -> list[dict]:
    specs = _specs_from_workers(inputs, warnings)
    specs.extend(_specs_from_rates_and_quantities(inputs))
    return _dedupe_specs(specs)


# ── 표준품셈 RAG ───────────────────────────────────────────────────────────────

def _normalize_labor_job_name(text: str) -> str:
    normalized = re.sub(r"\s+", "", str(text or ""))
    aliases = {
        "방수공": "방수공",
        "보통인부": "보통인부",
        "콘크리트공": "콘크리트공",
        "철골공": "철골공",
        "철근공": "철근공",
        "비계공": "비계공",
        "용접공": "용접공",
        "특별인부": "특별인부",
    }
    return aliases.get(normalized, normalized)


def _combined_input_text(inputs: dict) -> str:
    parts = []
    work_type = inputs.get("work_type") if isinstance(inputs.get("work_type"), dict) else {}
    parts.append(str(work_type.get("raw_text") or ""))
    for item in _as_list(inputs.get("quantities")):
        if isinstance(item, dict):
            parts.extend(str(item.get(key) or "") for key in ("material_name", "item_name", "name", "unit"))
        else:
            parts.append(str(item or ""))
    return " ".join(part for part in parts if part).lower()


def _select_standard_spec_query(inputs: dict) -> tuple[str | None, str | None]:
    text = _combined_input_text(inputs)
    if any(keyword in text for keyword in ("철골", "steel")):
        return "철골 세우기 표준품셈 기본철골공수 인일 t", "steel"
    if any(keyword in text for keyword in ("콘크리트", "타설", "concrete")):
        return "콘크리트 타설 표준품셈 콘크리트공 보통인부 품량", "concrete"
    if any(keyword in text for keyword in ("우레탄", "도막", "도막바름", "고무계")):
        return "6-2-1 도막바름 우레탄 방수공 보통인부", "waterproofing_membrane"
    if any(keyword in text for keyword in ("방수", "우레탄", "도막", "시트", "waterproof")):
        return "방수 표준품셈 방수공 보통인부 품량", "waterproofing"
    return None, None


def _quantity_for_standard_spec(inputs: dict, domain_type: str) -> float | None:
    quantities = _as_list(inputs.get("quantities"))
    if not quantities:
        return None

    preferred_terms = {
        "waterproofing": ("방수", "우레탄", "도막", "시트"),
        "waterproofing_membrane": ("방수", "우레탄", "도막"),
        "concrete": ("콘크리트", "타설"),
        "steel": ("철골",),
    }.get(domain_type, ())

    for item in quantities:
        if not isinstance(item, dict):
            continue
        label = " ".join(
            str(item.get(key) or "")
            for key in ("material_name", "item_name", "name", "unit")
        )
        if preferred_terms and any(term in label for term in preferred_terms):
            value = _quantity_value(item)
            if value is not None:
                return value

    if len(quantities) == 1:
        return _quantity_value(quantities[0])
    return None


def _parse_labor_units_from_standard_spec(content: str, domain_type: str) -> list[dict]:
    text = str(content or "")
    parsed: list[dict] = []

    if domain_type in {"waterproofing", "waterproofing_membrane"}:
        for raw_job in ("방\\s*수\\s*공", "보\\s*통\\s*인\\s*부"):
            pattern = rf"({raw_job})\s+인\s+([0-9]+(?:\.[0-9]+)?)"
            match = re.search(pattern, text)
            if not match:
                continue
            parsed.append({
                "job_type": _normalize_labor_job_name(match.group(1)),
                "unit_labor": float(match.group(2)),
                "unit": "㎡",
                "spec": (
                    "표준품셈 6-2-1 도막바름"
                    if domain_type == "waterproofing_membrane"
                    else "표준품셈 방수공사"
                ),
            })

    elif domain_type == "concrete":
        by_job: dict[str, dict] = {}
        pattern = r"(콘크리트공|보통인부)\s*:\s*.*?=\s*([0-9]+(?:\.[0-9]+)?)\s*인\s*/\s*(?:㎥|m3|m³)"
        for match in re.finditer(pattern, text):
            job_type = _normalize_labor_job_name(match.group(1))
            by_job[job_type] = {
                "job_type": job_type,
                "unit_labor": float(match.group(2)),
                "unit": "㎥",
                "spec": "표준품셈 레디믹스트콘크리트 타설",
            }
        parsed.extend(by_job.values())

    elif domain_type == "steel":
        if not re.search(r"기\s*본\s*철\s*골\s*공\s*수", text):
            return []
        if not re.search(r"인\s*[･·ㆍ\.\-]?\s*일\s*/\s*t", text, flags=re.IGNORECASE):
            return []

        anchor = re.search(r"기\s+본\s+철\s+골\s+공\s+수", text)
        tail = text[anchor.end(): anchor.end() + 200] if anchor else text
        match = re.search(r"([0-9]+(?:\.[0-9]+)?)", tail)
        if match:
            parsed.append({
                "job_type": "철골공",
                "unit_labor": float(match.group(1)),
                "unit": "t",
                "spec": "표준품셈 기본철골공수",
            })

    return parsed


def _is_standard_spec_content_acceptable(content: str, domain_type: str) -> bool:
    text = str(content or "")
    if domain_type == "waterproofing_membrane":
        return ("도막" in text or "우레탄" in text or "고무계" in text) and "자착식시트" not in text
    return True


def _search_membrane_waterproofing_by_keyword() -> list[str]:
    """우레탄/도막 방수 표준품셈 키워드 조회 — tools core 위임."""
    return _search_membrane_waterproofing_by_keyword_core()


def _infer_specs_from_standard_spec_rag(
    inputs: dict, warnings: list
) -> tuple[list[dict], list[dict], list[str]]:
    query, domain_type = _select_standard_spec_query(inputs)
    if not query or not domain_type:
        return [], [], []

    quantity = _quantity_for_standard_spec(inputs, domain_type)
    if quantity is None:
        warnings.append("표준품셈 RAG 추정을 위해 필요한 작업 물량(quantity)을 확인하지 못했습니다.")
        return [], [], []

    try:
        search = _search_standard_spec_core(query)
    except Exception as exc:
        warnings.append(f"표준품셈 RAG 검색 중 오류가 발생해 인건비 추정을 건너뛰었습니다: {exc}")
        _log.exception("standard spec RAG lookup failed")
        return [], [], []

    chunks = search.get("chunks") or []
    if not search.get("found") or not chunks:
        warnings.append("표준품셈 RAG에서 해당 공종의 품량 근거를 찾지 못했습니다.")
        return [], [], []

    def _build_from_chunks(candidate_chunks: list) -> tuple[list[dict], list[dict]]:
        built_specs: list[dict] = []
        built_evidence: list[dict] = []
        for content in candidate_chunks:
            if not _is_standard_spec_content_acceptable(str(content), domain_type):
                continue
            parsed_units = _parse_labor_units_from_standard_spec(content, domain_type)
            if not parsed_units:
                continue
            for unit in parsed_units:
                built_specs.append({
                    "job_type": unit["job_type"],
                    "quantity": quantity,
                    "unit_labor": unit["unit_labor"],
                    "source": "standard_spec_rag",
                    "spec": unit["spec"],
                    "input_unit": unit["unit"],
                })
            built_evidence.append({
                "source": "rag.standard_spec",
                "type": "standard_spec",
                "content": str(content)[:1200],
                "usage": f"{domain_type} 표준품셈 단위 품량 추정",
            })
            break
        return built_specs, built_evidence

    specs, evidence = _build_from_chunks(chunks)

    if not specs and domain_type == "waterproofing_membrane":
        try:
            specs, evidence = _build_from_chunks(_search_membrane_waterproofing_by_keyword())
        except Exception as exc:
            warnings.append(f"우레탄/도막 방수 표준품셈 키워드 조회 중 오류가 발생했습니다: {exc}")
            _log.exception("membrane waterproofing standard spec keyword lookup failed")

    if not specs and domain_type == "steel":
        try:
            steel_search = _search_standard_spec_core(
                "철골 세우기 표준품셈 기본철골공수 인일 t 철골공 비계 용접"
            )
            specs, evidence = _build_from_chunks(steel_search.get("chunks") or [])
        except Exception as exc:
            warnings.append(f"철골 기본철골공수 보조 RAG 검색 중 오류가 발생했습니다: {exc}")
            _log.exception("steel standard spec fallback lookup failed")

    assumptions = ["표준품셈 RAG 검색 결과를 기반으로 직종별 단위 품량을 추정했습니다."]

    if not specs:
        warnings.append("표준품셈 RAG content에서 직종별 품량을 파싱하지 못했습니다.")
        return [], [], []

    if domain_type == "steel":
        assumptions.append(
            "철골 세우기는 표준품셈의 기본철골공수(인·일/t)를 철골공 기준 대표 공수로 적용했습니다. "
            "비계 및 보조공은 기본공수에 포함된 것으로 보며, 용접품은 별도 계상 대상입니다."
        )
        warnings.append("철골 세우기 인건비는 직종별 세부 분해가 아닌 기본철골공수 기반 추정값입니다.")

    return _dedupe_specs(specs), evidence, assumptions


# ── 핵심 계산 ──────────────────────────────────────────────────────────────────

def _missing_input_result(inputs: dict, warnings: list) -> dict:
    result = _base_result("MISSING_INFO", "인건비 계산에 필요한 직종별 투입 정보가 부족합니다.")
    for field in _as_list(inputs.get("missing_fields")):
        _append_unique(result["missing_fields"], field)
    for field in ("job_type", "workers_or_quantity_unit_labor"):
        _append_unique(result["missing_fields"], field)
    result["warnings"].extend(warnings)
    result["warnings"].append(
        "workers 또는 rates/quantities에 직종명과 투입 인원/일수 또는 quantity+unit_labor 조합을 구조적으로 제공해야 합니다."
    )
    return result


def _build_cost_item(job_type: str, price_info: dict, workers_info: dict, cost_info: dict, spec: dict) -> dict:
    workers = workers_info["total_workers"] if "total_workers" in workers_info else workers_info["workers"]
    quantity = workers
    formula_left = f"{price_info['price']:,}원 × {workers:g}인"

    if spec.get("quantity") is not None and spec.get("unit_labor") is not None:
        quantity = workers
        formula_left = (
            f"{spec['quantity']:g} × {spec['unit_labor']:g} = {workers:g}인, "
            f"{price_info['price']:,}원 × {workers:g}인"
        )

    return {
        "name": f"{job_type} 인건비",
        "category": "labor",
        "job_type": job_type,
        "spec": spec.get("spec") or "사용자 구조화 입력",
        "quantity": quantity,
        "unit": "인",
        "unit_price": price_info["price"],
        "amount": cost_info["total"],
        "formula": f"{formula_left} = {cost_info['total']:,}원",
    }


def _calculate_result(inputs: dict) -> dict:
    warnings: list[str] = []
    specs = _collect_specs(inputs, warnings)
    rag_evidence: list[dict] = []
    rag_assumptions: list[str] = []

    if not specs:
        inferred_specs, rag_evidence, rag_assumptions = _infer_specs_from_standard_spec_rag(inputs, warnings)
        specs.extend(inferred_specs)
        if not specs:
            return _missing_input_result(inputs, warnings)

    result = _base_result("CALCULATED", "인건비를 deterministic core 함수로 계산했습니다.")
    if rag_assumptions:
        result["assumptions"].extend(rag_assumptions)
        result["evidence"].extend(rag_evidence)
    else:
        result["assumptions"].append("입력된 직종별 투입 정보만 사용했으며 누락 값은 추정하지 않았습니다.")
    result["warnings"].extend(warnings)

    failed_specs = 0
    db_errors = 0

    for spec in specs:
        job_type = spec.get("job_type")
        if not job_type:
            failed_specs += 1
            _append_unique(result["missing_fields"], "job_type")
            result["warnings"].append("직종명이 없는 인건비 입력 항목은 계산에서 제외했습니다.")
            continue

        workers = _to_number(spec.get("workers"))
        workers_info: dict | None = None
        if workers is not None:
            workers_info = {"workers": workers}
        elif spec.get("quantity") is not None and spec.get("unit_labor") is not None:
            workers_info = _calculate_workers_core(float(spec["quantity"]), float(spec["unit_labor"]))
            workers = _to_number(workers_info.get("total_workers"))

        if workers is None:
            failed_specs += 1
            _append_unique(result["missing_fields"], f"{job_type}: workers_or_quantity_unit_labor")
            result["warnings"].append(
                f"{job_type} 항목에 workers 또는 quantity+unit_labor 조합이 없어 계산에서 제외했습니다."
            )
            continue

        try:
            price_info = _get_labor_price_core(job_type)
        except Exception as exc:
            failed_specs += 1
            db_errors += 1
            _append_unique(result["missing_fields"], f"{job_type}: labor_price")
            result["warnings"].append(f"{job_type} 노임단가 DB 조회 중 오류가 발생했습니다: {exc}")
            _log.exception("labor price lookup failed for %s", job_type)
            continue

        if not price_info.get("found"):
            failed_specs += 1
            _append_unique(result["missing_fields"], f"{job_type}: labor_price")
            result["warnings"].append(f"노임단가 DB에서 직종을 찾지 못했습니다: {job_type}")
            continue

        cost_info = _calculate_labor_cost_core(int(price_info["price"]), float(workers))
        result["cost_items"].append(
            _build_cost_item(job_type, price_info, workers_info, cost_info, spec)
        )
        result["evidence"].append({
            "source": "labor_cost.labor_cost",
            "type": "labor_db",
            "content": f"{price_info['job_type']}: {price_info['price']:,}원 ({price_info['year']} 기준)",
            "usage": f"{job_type} 노임단가 적용",
        })

    result["total_cost"] = sum(item["amount"] for item in result["cost_items"])

    if result["cost_items"] and failed_specs:
        result["status"] = "PARTIAL"
        result["summary"] = "일부 직종의 인건비만 계산했습니다."
    elif result["cost_items"]:
        result["status"] = "CALCULATED"
        result["summary"] = f"인건비 {result['total_cost']:,}원을 계산했습니다."
    elif db_errors and failed_specs == len(specs):
        result["status"] = "ERROR"
        result["summary"] = "노임단가 DB 조회 오류로 인건비를 계산하지 못했습니다."
    else:
        result["status"] = "MISSING_INFO"
        result["summary"] = "노임단가 또는 투입 정보 부족으로 인건비를 계산하지 못했습니다."

    return result


# ── 공개 API ───────────────────────────────────────────────────────────────────

def calculate_labor_cost(inputs: dict | None) -> dict:
    """인건비 계산 진입점.

    Args:
        inputs: extractor_node가 생성한 state['inputs'] dict.
                None 또는 비-dict인 경우 MISSING_INFO 결과를 반환한다.

    Returns:
        aggregator 계약(labor_cost_result schema)을 만족하는 result dict.
    """
    if not isinstance(inputs, dict):
        result = _base_result("MISSING_INFO", "인건비 계산 입력이 구조화 dict가 아닙니다.")
        result["missing_fields"].append("inputs")
        result["warnings"].append("extractor_node가 생성한 state['inputs'] dict가 필요합니다.")
        return result
    return _calculate_result(inputs)
